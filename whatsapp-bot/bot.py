"""Telegram-WhatsApp bridge bot.

This module houses the Telegram bot application and orchestrates the WhatsApp bridge
workflow: polling WhatsApp DB, batching fragmented texts, generating AI replies,
logging to Google Sheets, and presenting approval cards to Telegram for human-in-the-loop.

Key responsibilities:
- Monitor the WhatsApp SQLite DB (via the Go bridge) for new inbound messages
- Batch short/fragmented texts per chat for a configurable idle window (default 20 min)
- Generate suggested replies using OpenAI with recent conversation context
- Forward media previews to Telegram and present approval actions
- Send approved replies/media back to WhatsApp via the bridge REST API
"""
# bot.py
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

import sqlite3
import os
import requests
import time
import json
from datetime import datetime
from openai import OpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import gspread
from google.oauth2.service_account import Credentials
import asyncio
from config import *
from helpers import ai_utils, media_utils, queue_utils, batch_utils, telegram_utils, whatsapp_api
import logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO  # Changed to INFO to reduce noise
)


class WhatsAppAIBot:
    """Main application class for the Telegram-facing approval bot.

    Creates the Telegram app, manages batching state, and coordinates the
    end-to-end flow from WhatsApp -> Telegram -> WhatsApp.
    """
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.last_processed_timestamp = datetime.now()
        self.pending_approvals = {}  # Store pending AI replies
        self.processed_message_ids = set()  # Track processed message IDs to avoid duplicates
        self.first_card_sent = False  # Controls timestamp wording on first presented item
        # Batch window (seconds) for concatenating short/fragmented texts before AI
        # Default 20 minutes, can be overridden with BATCH_WINDOW_SEC env var
        batch_window = os.getenv("BATCH_WINDOW_SEC", "1200")
        try:
            self.batch_window_sec = int(batch_window)
        except ValueError:
            self.batch_window_sec = 1200  # Default to 20 minutes if invalid
        print(f"⏱️  Batch window: {self.batch_window_sec} seconds ({self.batch_window_sec // 60} minutes)", flush=True)
        # Per-chat buffer: chat_jid -> {texts: [str], last_msg_id: str, sender_name: str, last_timestamp: datetime}
        self.incoming_buffers = {}
        
        # Google Sheets setup
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=scopes)
        self.sheets_client = gspread.authorize(creds)
        self.sheet = self.sheets_client.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME)
        
        # Initialize sheet headers if empty
        if not self.sheet.row_values(1):
            self.sheet.append_row(
                ['Timestamp', 'Sender ID', 'Sender Name', 'Incoming Message', 'AI Reply', 'Status', 'Final Reply Sent'])

        # Build Telegram Application
        # Telegram app with shorter timeouts to reduce callback timeouts
        req = HTTPXRequest(connect_timeout=5.0, read_timeout=5.0, write_timeout=5.0, pool_timeout=5.0)
        self.telegram_app = (
            Application
            .builder()
            .token(TELEGRAM_BOT_TOKEN)
            .request(req)
            .build()
        )

        # Register handlers - Order matters!
        self.telegram_app.add_handler(CommandHandler("start", self.start_command))
        self.telegram_app.add_handler(CommandHandler("logout", self.cmd_logout))
        self.telegram_app.add_handler(CommandHandler("login", self.cmd_login))
        self.telegram_app.add_handler(CommandHandler("queue", self.cmd_queue))
        self.telegram_app.add_handler(CommandHandler("next", self.cmd_next))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_approve, pattern=r"^approve_"))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_record_own, pattern=r"^record_"))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_reject, pattern=r"^reject_"))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_reply_later, pattern=r"^later_"))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_custom_init, pattern=r"^custom_"))
        self.telegram_app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        self.telegram_app.add_handler(MessageHandler(filters.PHOTO, self.handle_custom_photo))
        self.telegram_app.add_handler(MessageHandler(filters.Document.ALL, self.handle_custom_document))
        self.telegram_app.add_handler(MessageHandler(filters.VIDEO, self.handle_custom_video))
        self.telegram_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_custom_text))

        # Ensure queue table exists (persisted alongside messages DB)
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT,
                    chat_jid TEXT,
                    sender_name TEXT,
                    content TEXT,
                    media_type TEXT,
                    media_path TEXT,
                    ai_reply TEXT,
                    row_number INTEGER,
                    status TEXT,
                    priority INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_transition_at TIMESTAMP
                );
                """
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Failed to ensure queue table: {e}", flush=True)
    
    # ==================== Batch Buffer Helpers ====================
    def _buffer_add_text(self, chat_jid: str, msg_id: str, sender_name: str, text: str, timestamp):
        batch_utils.buffer_add_text(self, chat_jid, msg_id, sender_name, text, timestamp)

    def _flush_ready_buffers(self) -> bool:
        return batch_utils.flush_ready_buffers(self)
    
    # ==================== PHASE 1: Message Detection ====================
    def get_new_messages(self):
        """Monitor database for new messages"""
        try:
            # Convert to absolute path
            db_path = os.path.abspath(DATABASE_PATH) if not os.path.isabs(DATABASE_PATH) else DATABASE_PATH
            if not os.path.exists(db_path):
                print(f"⚠️  Database not found at: {db_path}", flush=True)
                return []
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Convert datetime to string for SQLite comparison
            timestamp_str = self.last_processed_timestamp.strftime("%Y-%m-%d %H:%M:%S")
            
            query = """
                SELECT m.id, m.chat_jid, m.sender, m.content, m.timestamp, c.name, m.media_type
                FROM messages m
                LEFT JOIN chats c ON m.chat_jid = c.jid
                WHERE m.timestamp > ? 
                AND m.is_from_me = 0
                      AND (m.content != '' OR m.media_type != '')
                    ORDER BY m.timestamp ASC
            """
            
            cursor.execute(query, (timestamp_str,))
            messages = cursor.fetchall()
            conn.close()
            
            return messages
        except Exception as e:
            print(f"❌ Error reading database: {e}", flush=True)
            print(f"   Database path: {DATABASE_PATH}", flush=True)
            return []
    
    def transcribe_voice_message(self, message_id, chat_jid):
        """Download and transcribe a WhatsApp voice message via the bridge."""
        return ai_utils.transcribe_voice_message(self, message_id, chat_jid)
    
    # ==================== PHASE 2: AI Reply Generation ====================
    def generate_ai_reply(self, sender_jid, message_text):
        """Generate a suggested reply using recent conversation context."""
        return ai_utils.generate_ai_reply(self, sender_jid, message_text)
    
    # ==================== Media Download & Telegram Send ====================
    def download_media(self, message_id, chat_jid):
        """Ask the bridge to download media for a given message and return paths."""
        return media_utils.download_media(self, message_id, chat_jid)

    async def send_telegram_media(self, media_type, media_path, caption):
        """Send media to Telegram with appropriate method (photo/video/document)."""
        await media_utils.send_telegram_media(self, media_type, media_path, caption)

    def find_recent_media_in_store(self, chat_jid: str) -> str:
        """Heuristic fallback to resolve a recent file under store/<chat>."""
        return media_utils.find_recent_media_in_store(chat_jid)

    def get_media_size_bytes(self, message_id: str, chat_jid: str) -> int:
        """Read media size from DB if available; 0 if unknown."""
        return media_utils.get_media_size_bytes(DATABASE_PATH, message_id, chat_jid)

    def format_size(self, num_bytes: int) -> str:
        """Human-readable file size string."""
        return media_utils.format_size(num_bytes)

    # ==================== Queue Helpers ====================
    def is_greeting(self, text: str) -> bool:
        """Return True if text looks like a short greeting (higher priority)."""
        return queue_utils.is_greeting(text)

    def enqueue_item(self, message_id, chat_jid, sender_name, content, media_type, media_path, ai_reply, row_number):
        """Insert item into the approval queue with greeting-aware priority."""
        priority = 50 if self.is_greeting(content or "") else 20
        queue_utils.enqueue_item(DATABASE_PATH, message_id, chat_jid, sender_name, content, media_type, media_path, ai_reply, row_number, priority)

    def get_active_item(self):
        """Return the currently active queue item, if any."""
        return queue_utils.get_active_item(DATABASE_PATH)

    def activate_next_pending(self):
        """Promote the next pending item to active state and return it."""
        return queue_utils.activate_next_pending(DATABASE_PATH)

    def mark_item_status(self, qid: int, status: str):
        """Update a queue item's status and timestamp."""
        queue_utils.mark_item_status(DATABASE_PATH, qid, status)

    def pending_count(self) -> int:
        """Return count of items currently pending approval."""
        return queue_utils.pending_count(DATABASE_PATH)

    async def safe_edit(self, query, text, parse_mode=None):
        """Safely edit a Telegram message or caption depending on payload type."""
        await telegram_utils.safe_edit(query, text, parse_mode)

    async def present_active_item(self, item):
        """Render the active queue item as a Telegram card (text or media).

        Includes age, sender, and AI suggestion, with inline actions.
        """
        if not item:
            return
        qid, msg_id, chat_jid, sender_name, content, media_type, media_path, ai_reply, row_number = item
        # compute age
        age = "just now"
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor(); cur.execute("SELECT timestamp FROM messages WHERE id=? AND chat_jid=?", (msg_id, chat_jid))
            r = cur.fetchone(); conn.close()
            if r and r[0]:
                t = r[0]
                if isinstance(t, str):
                    t = datetime.fromisoformat(t.replace(' ', 'T'))
                delta = datetime.now() - t
                mins = int(delta.total_seconds() // 60)
                if mins < 1: age = "just now"
                elif mins < 60: age = f"{mins}m ago"
                else: age = f"{mins//60}h ago"
        except Exception:
            pass

        # Ensure we have a local media path for attachments (always refresh from bridge)
        if media_type in ("image", "video", "document"):
            try:
                ok, _, _, p = self.download_media(msg_id, chat_jid)
                if ok and p:
                    media_path = p
                    print(f"Media path resolved: {media_path}", flush=True)
                else:
                    print(f"Media download returned no path for {msg_id}", flush=True)
                    # Fallback: pick the latest file in chat directory
                    fp = self.find_recent_media_in_store(chat_jid)
                    if fp:
                        media_path = fp
                        print(f"Fallback media path: {media_path}", flush=True)
            except Exception as e:
                print(f"Media fetch fallback failed: {e}", flush=True)
        # We'll attach the media with the approval buttons instead of sending a separate preview

        self.pending_approvals[msg_id] = {'sender_id': chat_jid, 'ai_reply': ai_reply, 'row_number': row_number}

        display = content or "[Media only]"
        # Fetch absolute timestamp string for first card wording
        sent_line = f"🕒 Received: {age}"
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor(); cur.execute("SELECT timestamp FROM messages WHERE id=? AND chat_jid=?", (msg_id, chat_jid))
            r = cur.fetchone(); conn.close()
            if not self.first_card_sent and r and r[0]:
                ts = r[0]
                if isinstance(ts, str):
                    # keep as-is, already stored in DB format
                    sent_line = f"🕒 Sent at: {ts}"
                else:
                    sent_line = f"🕒 Sent at: {ts.strftime('%Y-%m-%d %H:%M:%S')}"
        except Exception:
            pass

        text = f"""🔔 *New WhatsApp Message*

👤 *From:* {sender_name or chat_jid}
📱 *Number:* {chat_jid}
{sent_line}

💬 *Message:*
{display}

🤖 *AI Suggested Reply:*
{ai_reply}
"""
        keyboard = telegram_utils.build_full_approval_keyboard(msg_id)
        try:
            print(f"Sending media card: type={media_type} path={media_path}", flush=True)
            if media_type in ("image", "video", "document") and media_path:
                # For media, send the file with minimal caption (no AI reply or "Media only").
                caption_media = f"""🔔 *New WhatsApp Media*

👤 *From:* {sender_name or chat_jid}
📱 *Number:* {chat_jid}
{sent_line}
"""
                if media_type == "image":
                    with open(media_path, "rb") as f:
                        await self.telegram_app.bot.send_photo(chat_id=YOUR_TELEGRAM_CHAT_ID, photo=f, caption=caption_media, reply_markup=InlineKeyboardMarkup(keyboard))
                elif media_type == "video":
                    with open(media_path, "rb") as f:
                        await self.telegram_app.bot.send_video(chat_id=YOUR_TELEGRAM_CHAT_ID, video=f, caption=caption_media, reply_markup=InlineKeyboardMarkup(keyboard))
                else:
                    with open(media_path, "rb") as f:
                        await self.telegram_app.bot.send_document(chat_id=YOUR_TELEGRAM_CHAT_ID, document=f, caption=caption_media, reply_markup=InlineKeyboardMarkup(keyboard))
                self.first_card_sent = True
                return
            else:
                await self.telegram_app.bot.send_message(chat_id=YOUR_TELEGRAM_CHAT_ID, text=text, reply_markup=keyboard, parse_mode='Markdown')
        except Exception as e:
            print(f"Failed to send approval card: {e}", flush=True)
        # After first present, switch to relative wording for subsequent items
        self.first_card_sent = True
    
    # ==================== PHASE 3: Google Sheets Logging ====================
    def log_to_sheets(self, timestamp, sender_id, sender_name, incoming_msg, ai_reply, status="Pending",
                      final_reply=""):
        """Append a single row to the Google Sheet for auditing and status tracking."""
        # Convert timestamp if it's a string
        if isinstance(timestamp, str):
            from datetime import datetime
            timestamp = datetime.fromisoformat(timestamp.replace(' ', 'T'))
        
        row = [
            timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            sender_id,
            sender_name or sender_id,
            incoming_msg,
            ai_reply,
            status,
            final_reply
        ]
        self.sheet.append_row(row)
        return len(self.sheet.get_all_values())  # Return row number
    
    # ==================== PHASE 4: Telegram Notification ====================
    async def send_telegram_notification(self, sender_name, sender_id, incoming_msg, ai_reply, message_id,
                                         is_voice=False):
        """Send a simplified notification card to Telegram (used in some flows)."""
        message_type = "🎤 *Voice Message (Transcribed)*" if is_voice else "💬 *Message:*"
        
        text = f"""🔔 *New WhatsApp Message*
        
👤 *From:* {sender_name or sender_id}
📱 *Number:* {sender_id}

{message_type}
{incoming_msg}

🤖 *AI Suggested Reply:*
{ai_reply}
"""
        
        reply_markup = telegram_utils.build_notification_keyboard(message_id)
        
        # Store pending approval without losing an existing row_number
        existing = self.pending_approvals.get(message_id, {})
        self.pending_approvals[message_id] = {
            'sender_id': sender_id,
            'ai_reply': ai_reply,
            'row_number': existing.get('row_number')
        }
        
        return await self.telegram_app.bot.send_message(
            chat_id=YOUR_TELEGRAM_CHAT_ID,
            text=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    # ==================== PHASE 5: Approval System ====================
    async def handle_approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle Approve & Send action.

        Looks up the pending approval context, sends via the bridge, updates
        Google Sheets, marks queue item done, then advances to the next.
        """
        query = update.callback_query
        try:
            await query.answer()
        except Exception as e:
            print(f"query.answer failed: {e}", flush=True)
        
        message_id = query.data.replace("approve_", "")
        print(
            f"\n{'=' * 60}\n[APPROVE BUTTON CLICKED]\nMessage ID: {message_id}\n{'=' * 60}\n",
            flush=True,
        )

        # Resolve approval context
        approval = self.pending_approvals.get(message_id)
        if not approval:
            try:
                conn = sqlite3.connect(DATABASE_PATH)
                cur = conn.cursor()
                cur.execute(
                    "SELECT chat_jid, ai_reply, row_number FROM queue_items WHERE message_id=? ORDER BY last_transition_at DESC, id DESC LIMIT 1",
                    (message_id,),
                )
                r = cur.fetchone()
                conn.close()
                if r:
                    approval = {"sender_id": r[0], "ai_reply": r[1], "row_number": r[2]}
                    self.pending_approvals[message_id] = approval
            except Exception as e:
                print(f"Recovery lookup failed: {e}", flush=True)

        if not approval:
            print(f"❌ No approval found for message_id: {message_id}", flush=True)
            await self.safe_edit(query, "⚠️ This request has expired or was already processed.")
            try:
                conn = sqlite3.connect(DATABASE_PATH)
                cur = conn.cursor()
                cur.execute(
                    "UPDATE queue_items SET status='pending', last_transition_at=CURRENT_TIMESTAMP WHERE status='active' AND message_id=?",
                    (message_id,),
                )
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Queue reset on expired failed: {e}", flush=True)
            nxt = self.activate_next_pending()
            if nxt:
                await self.present_active_item(nxt)
            return
        
        # Try to send (wrap entire send and branches in one try)
        try:
            print(f"📤 Sending to WhatsApp...", flush=True)
            print(f"   Recipient: {approval['sender_id']}", flush=True)
            print(f"   Message: {approval['ai_reply']}", flush=True)

            success = self.send_whatsapp_message(approval["sender_id"], approval["ai_reply"])
            if success:
                if approval.get("row_number"):
                    self.update_sheet_status(approval["row_number"], "Sent (AI Reply)", approval["ai_reply"])
                await self.safe_edit(
                    query,
                    f"✅ *Message Approved & Sent!*\n\nSent to: {approval['sender_id']}\nReply: {approval['ai_reply']}",
                    parse_mode="Markdown",
                )
                try:
                    conn = sqlite3.connect(DATABASE_PATH)
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id FROM queue_items WHERE message_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                        (message_id,),
                    )
                    r = cur.fetchone()
                    conn.close()
                    if r:
                        self.mark_item_status(r[0], "done")
                except Exception:
                    pass
                nxt = self.activate_next_pending()
                if nxt:
                    await self.present_active_item(nxt)
            else:
                await self.safe_edit(
                    query,
                    "❌ Failed to send message to WhatsApp. Check bridge/API.",
                    parse_mode="Markdown",
                )
        except Exception as e:
            print(f"❌ Error in handle_approve: {e}", flush=True)
            import traceback
            traceback.print_exc()
            await self.safe_edit(query, f"❌ Error: {str(e)}")
    
    async def handle_record_own(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle 'Record Own' button click"""
        query = update.callback_query
        await query.answer()
        
        # Extract message_id
        message_id = query.data.replace("record_", "")
        print(f"\n[RECORD OWN BUTTON CLICKED] Message ID: {message_id}", flush=True)

        approval = self.pending_approvals.get(message_id)
        
        if not approval:
            await query.edit_message_text("⚠️ This request has expired.")
            return
        
        # Store in context for voice handler
        context.user_data['pending_voice'] = message_id
        
        await query.edit_message_text(
            "🎤 *Ready to record!*\n\n"
            "Please send your voice message now.\n"
            "I'll forward it to the WhatsApp contact.",
            parse_mode='Markdown'
        )
        print(f"✅ Ready to receive voice message", flush=True)
    
    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle a Telegram voice note recorded as a manual reply and relay to WhatsApp."""
        print(f"\n[VOICE MESSAGE RECEIVED]", flush=True)
        
        if 'pending_voice' not in context.user_data:
            await update.message.reply_text("⚠️ No pending message. Click 'Record Own' first.")
            return
        
        message_id = context.user_data['pending_voice']
        approval = self.pending_approvals.get(message_id)
        
        if not approval:
            await update.message.reply_text("❌ Request expired.")
            del context.user_data['pending_voice']
            return
        
        try:
            # Download voice message
            voice = update.message.voice
            file = await voice.get_file()
            voice_path = f"voice_{message_id}.ogg"
            await file.download_to_drive(voice_path)
            
            print(f"Voice downloaded to: {voice_path}", flush=True)
            
            # Get absolute path
            import os
            abs_voice_path = os.path.abspath(voice_path)
            
            # Send voice to WhatsApp
            success = self.send_whatsapp_voice(approval['sender_id'], abs_voice_path)
            
            if success:
                self.update_sheet_status(approval['row_number'], "Sent (Manual Voice)", "[Voice Message]")
                await update.message.reply_text("✅ *Voice message sent successfully!*", parse_mode='Markdown')
                # mark done and advance
                try:
                    conn = sqlite3.connect(DATABASE_PATH)
                    cur = conn.cursor(); cur.execute("SELECT id FROM queue_items WHERE message_id=? AND status='active' ORDER BY id DESC LIMIT 1", (message_id,))
                    r = cur.fetchone(); conn.close()
                    if r:
                        self.mark_item_status(r[0], 'done')
                except Exception:
                    pass
                nxt = self.activate_next_pending()
                if nxt:
                    await self.present_active_item(nxt)
            else:
                await update.message.reply_text("❌ Failed to send voice message. Check WhatsApp bridge.")
            
            del context.user_data['pending_voice']
            
        except Exception as e:
            print(f"Error sending voice: {e}", flush=True)
            await update.message.reply_text(f"❌ Error: {str(e)}")
            del context.user_data['pending_voice']
    
    async def handle_reply_later(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Defer the active item by moving it back to pending, then show next."""
        query = update.callback_query
        await query.answer()
        message_id = query.data.replace("later_", "")
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM queue_items WHERE message_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                (message_id,),
            )
            row = cur.fetchone()
            if row:
                # Move back to pending (defer)
                cur.execute(
                    "UPDATE queue_items SET status='pending', last_transition_at=CURRENT_TIMESTAMP WHERE id=?",
                    (row[0],),
                )
                conn.commit()
            conn.close()
            await query.edit_message_text("\u23F3 Deferred. Showing next message.")
        except Exception as e:
            print(f"Failed to defer item: {e}", flush=True)
            await query.edit_message_text("\u274C Could not defer. Try again.")
        # Activate and present next pending
        nxt = self.activate_next_pending()
        if nxt:
            await self.present_active_item(nxt)

    async def handle_custom_init(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Begin custom reply flow; subsequent user message becomes the reply."""
        query = update.callback_query
        await query.answer()
        message_id = query.data.replace("custom_", "")
        context.user_data['custom_target'] = message_id
        await self.safe_edit(query, "✍️ Send your custom message now (text/photo/video/document/voice).")

    async def handle_custom_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle a free-form text reply for the selected WhatsApp chat."""
        if 'custom_target' not in context.user_data:
            return
        message_id = context.user_data['custom_target']
        approval = self.pending_approvals.get(message_id)
        if not approval:
            # recover from queue
            conn = sqlite3.connect(DATABASE_PATH); cur = conn.cursor()
            cur.execute("SELECT chat_jid FROM queue_items WHERE message_id=? ORDER BY id DESC LIMIT 1", (message_id,))
            r = cur.fetchone(); conn.close()
            if not r: return
            approval = {'sender_id': r[0], 'ai_reply': '', 'row_number': None}
        sent = self.send_whatsapp_message(approval['sender_id'], update.message.text)
        if sent:
            await update.message.reply_text("✅ Custom text sent.")
            # mark done and advance
            try:
                conn = sqlite3.connect(DATABASE_PATH); cur = conn.cursor()
                cur.execute("SELECT id FROM queue_items WHERE message_id=? AND status='active' ORDER BY id DESC LIMIT 1", (message_id,))
                r = cur.fetchone(); conn.close()
                if r: self.mark_item_status(r[0], 'done')
            except Exception: pass
            context.user_data.pop('custom_target', None)
            nxt = self.activate_next_pending()
            if nxt: await self.present_active_item(nxt)
        else:
            await update.message.reply_text("❌ Failed to send.")

    async def handle_custom_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle an image upload and forward it to WhatsApp for the target chat."""
        if 'custom_target' not in context.user_data: return
        message_id = context.user_data['custom_target']
        approval = self.pending_approvals.get(message_id)
        if not approval:
            conn = sqlite3.connect(DATABASE_PATH); cur = conn.cursor()
            cur.execute("SELECT chat_jid FROM queue_items WHERE message_id=? ORDER BY id DESC LIMIT 1", (message_id,))
            r = cur.fetchone(); conn.close()
            if not r: return
            approval = {'sender_id': r[0]}
        file = await update.message.photo[-1].get_file()
        local = f"custom_{message_id}.jpg"; await file.download_to_drive(local)
        try:
            resp = requests.post(f"{WHATSAPP_API_URL}/send", json={"recipient": approval['sender_id'], "message":"", "media_path": os.path.abspath(local)}, timeout=15)
            ok = resp.json().get('success', False)
        except Exception: ok=False
        await update.message.reply_text("✅ Custom image sent." if ok else "❌ Failed to send image. Tap Custom again to retry.")
        # Mark done and advance regardless to avoid blocking queue
        try:
            conn = sqlite3.connect(DATABASE_PATH); cur = conn.cursor()
            cur.execute("SELECT id FROM queue_items WHERE message_id=? AND status='active' ORDER BY id DESC LIMIT 1", (message_id,))
            r = cur.fetchone(); conn.close()
            if r: self.mark_item_status(r[0], 'done')
        except Exception: pass
        context.user_data.pop('custom_target', None)
        nxt = self.activate_next_pending()
        if nxt: await self.present_active_item(nxt)

    async def handle_custom_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle a document upload and forward it to WhatsApp for the target chat."""
        if 'custom_target' not in context.user_data: return
        message_id = context.user_data['custom_target']
        approval = self.pending_approvals.get(message_id)
        if not approval:
            conn = sqlite3.connect(DATABASE_PATH); cur = conn.cursor()
            cur.execute("SELECT chat_jid FROM queue_items WHERE message_id=? ORDER BY id DESC LIMIT 1", (message_id,))
            r = cur.fetchone(); conn.close()
            if not r: return
            approval = {'sender_id': r[0]}
        file = await update.message.document.get_file()
        local = f"custom_{message_id}_{update.message.document.file_name or 'doc'}"
        await file.download_to_drive(local)
        try:
            resp = requests.post(f"{WHATSAPP_API_URL}/send", json={"recipient": approval['sender_id'], "message":"", "media_path": os.path.abspath(local)}, timeout=30)
            ok = resp.json().get('success', False)
        except Exception: ok=False
        await update.message.reply_text("✅ Custom document sent." if ok else "❌ Failed to send document. Tap Custom again to retry.")
        try:
            conn = sqlite3.connect(DATABASE_PATH); cur = conn.cursor()
            cur.execute("SELECT id FROM queue_items WHERE message_id=? AND status='active' ORDER BY id DESC LIMIT 1", (message_id,))
            r = cur.fetchone(); conn.close()
            if r: self.mark_item_status(r[0], 'done')
        except Exception: pass
        context.user_data.pop('custom_target', None)
        nxt = self.activate_next_pending()
        if nxt: await self.present_active_item(nxt)

    async def handle_custom_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle a video upload and forward it to WhatsApp for the target chat."""
        if 'custom_target' not in context.user_data: return
        message_id = context.user_data['custom_target']
        approval = self.pending_approvals.get(message_id)
        if not approval:
            conn = sqlite3.connect(DATABASE_PATH); cur = conn.cursor()
            cur.execute("SELECT chat_jid FROM queue_items WHERE message_id=? ORDER BY id DESC LIMIT 1", (message_id,))
            r = cur.fetchone(); conn.close()
            if not r: return
            approval = {'sender_id': r[0]}
        file = await update.message.video.get_file()
        local = f"custom_{message_id}.mp4"; await file.download_to_drive(local)
        try:
            resp = requests.post(f"{WHATSAPP_API_URL}/send", json={"recipient": approval['sender_id'], "message":"", "media_path": os.path.abspath(local)}, timeout=60)
            ok = resp.json().get('success', False)
        except Exception: ok=False
        await update.message.reply_text("✅ Custom video sent." if ok else "❌ Failed to send video. Tap Custom again to retry.")
        try:
            conn = sqlite3.connect(DATABASE_PATH); cur = conn.cursor()
            cur.execute("SELECT id FROM queue_items WHERE message_id=? AND status='active' ORDER BY id DESC LIMIT 1", (message_id,))
            r = cur.fetchone(); conn.close()
            if r: self.mark_item_status(r[0], 'done')
        except Exception: pass
        context.user_data.pop('custom_target', None)
        nxt = self.activate_next_pending()
        if nxt: await self.present_active_item(nxt)
    async def handle_reject(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reject the current message and move on without sending."""
        query = update.callback_query
        await query.answer()
        message_id = query.data.replace("reject_", "")
        # Mark active as done/rejected and advance
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor(); cur.execute("SELECT id FROM queue_items WHERE message_id=? AND status='active' ORDER BY id DESC LIMIT 1", (message_id,))
            r = cur.fetchone();
            if r:
                self.mark_item_status(r[0], 'done')
            conn.close()
        except Exception as e:
            print(f"Reject mark failed: {e}", flush=True)
        await self.safe_edit(query, "⛔ Rejected. Moving to next.")
        nxt = self.activate_next_pending()
        if nxt:
            await self.present_active_item(nxt)
    
    # ==================== WhatsApp API Functions ====================
    def send_whatsapp_message(self, recipient, message):
        """Send text message to WhatsApp"""
        ok = whatsapp_api.send_text(recipient, message)
        return ok
    
    def send_whatsapp_voice(self, recipient, voice_path):
        """Send voice message to WhatsApp"""
        return whatsapp_api.send_voice(recipient, voice_path)
    
    # ==================== Helper Functions ====================
    def update_sheet_status(self, row_number, status, final_reply):
        """Update status in Google Sheets"""
        if row_number:
            self.sheet.update_cell(row_number, 6, status)  # Status column
            self.sheet.update_cell(row_number, 7, final_reply)  # Final reply column
    
    # ==================== PHASE 6: Main Loop ====================
    async def process_messages(self):
        """Main message processing loop"""
        print("\n🔄 Starting WhatsApp message monitoring...\n", flush=True)
        print(f"📂 Database path: {os.path.abspath(DATABASE_PATH)}", flush=True)
        print(f"📂 Database exists: {os.path.exists(os.path.abspath(DATABASE_PATH))}\n", flush=True)

        while True:
            try:
                # Check for new messages
                new_messages = self.get_new_messages()
                
                if new_messages:
                    print(f"📨 Found {len(new_messages)} new message(s)", flush=True)
                # Enqueue all first, then present one active to ensure pending count reflects full batch
                enqueued_any = False
                active_before = self.get_active_item()
                
                for msg_id, sender_jid, sender, content, timestamp, sender_name, media_type in new_messages:
                    # Skip if already processed
                    if msg_id in self.processed_message_ids:
                        print(f"⏭️  Skipping already processed message: {msg_id}", flush=True)
                        continue
                    
                    # Mark as processed
                    self.processed_message_ids.add(msg_id)
                    print(f"✅ Marked message {msg_id} as processed", flush=True)
                    
                    # Keep the set size manageable (keep last 1000 message IDs)
                    if len(self.processed_message_ids) > 1000:
                        self.processed_message_ids.pop()
                    
                    # Update last processed timestamp (convert from string to datetime)
                    if isinstance(timestamp, str):
                        from datetime import datetime
                        self.last_processed_timestamp = datetime.fromisoformat(timestamp.replace(' ', 'T'))
                    else:
                        self.last_processed_timestamp = timestamp
                    
                    # Handle media: keep audio path unchanged; handle images/videos/documents to Telegram
                    is_voice = False
                    if media_type == 'audio' and not content:
                        is_voice = True
                        print(f"🎤 Transcribing voice message from {sender_name or sender}...", flush=True)
                        content = self.transcribe_voice_message(msg_id, sender_jid)
                        if content:
                            print(f"Transcription: {content}", flush=True)
                        else:
                            print("Failed to transcribe voice message, skipping...", flush=True)
                            continue
                        # For voice (transcribed text), add to buffer and defer AI generation
                        self._buffer_add_text(sender_jid, msg_id, sender_name, content, timestamp)
                        # Do not enqueue now; will be flushed when idle
                        continue
                    elif media_type in ("image", "video", "document"):
                        ok, _, filename, path = self.download_media(msg_id, sender_jid)
                        if ok and path:
                            age = "just now"
                            try:
                                t = timestamp if not isinstance(timestamp, str) else datetime.fromisoformat(timestamp.replace(' ', 'T'))
                                delta = datetime.now() - t
                                mins = int(delta.total_seconds() // 60)
                                if mins < 1:
                                    age = "just now"
                                elif mins < 60:
                                    age = f"{mins}m ago"
                                else:
                                    hours = mins // 60
                                    age = f"{hours}h ago"
                            except Exception:
                                pass
                            size_str = self.format_size(self.get_media_size_bytes(msg_id, sender_jid))
                            name_part = f"\nFile: {filename}" if filename else ""
                            caption = f"📎 Media from {sender_name or sender}{name_part}\nType: {media_type}\nSize: {size_str}\nReceived: {age}"
                            await self.send_telegram_media(media_type, path, caption)
                            # Carry this path forward to enqueue
                            media_path_for_enqueue = path
                        else:
                            media_path_for_enqueue = ""

                    print(f"\n📨 Processing message from {sender_name or sender}: {content}", flush=True)

                    # If this is a plain text (or non-media) message, add to buffer and defer AI
                    if media_type not in ("image", "video", "document"):
                        self._buffer_add_text(sender_jid, msg_id, sender_name, content or "", timestamp)
                        buf = self.incoming_buffers.get(sender_jid)
                        if buf:
                            print(f"📝 Added to buffer (will wait {self.batch_window_sec // 60} min). Buffer now has {len(buf.get('texts', []))} message(s)", flush=True)
                        # Do not enqueue immediately; batching will flush later
                        continue

                    # Media messages proceed as before (AI for caption context if needed)
                    ai_reply = self.generate_ai_reply(sender_jid, content or "")
                    print(f"🤖 AI Reply: {ai_reply}", flush=True)
                    row_number = self.log_to_sheets(timestamp, sender_jid, sender_name, content or "", ai_reply)
                    media_path = locals().get('media_path_for_enqueue', "") if media_type in ("image", "video", "document") else ""
                    self.enqueue_item(msg_id, sender_jid, sender_name, content or "", media_type, media_path, ai_reply, row_number)
                    enqueued_any = True

                # Flush any buffered chats that are idle beyond the batch window
                if self.incoming_buffers:
                    print(f"⏳ Checking buffers... ({len(self.incoming_buffers)} chat(s) buffered)", flush=True)
                flushed = self._flush_ready_buffers()
                if flushed:
                    print(f"✅ Flushed buffered messages and sent to Telegram!", flush=True)
                enqueued_any = enqueued_any or flushed

                # After enqueueing, if nothing was active, present the next pending now
                if (not active_before) and enqueued_any:
                    nxt = self.activate_next_pending()
                    if nxt:
                        await self.present_active_item(nxt)
                
                # Sleep before next check
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                print(f"Error in main loop: {e}", flush=True)
                import traceback
                traceback.print_exc()
                await asyncio.sleep(10)  # Wait before retry
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await update.message.reply_text("🤖 WhatsApp AI Bot is running!\n\nI'm monitoring your WhatsApp messages...")
    
    async def cmd_logout(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Log out WhatsApp on the bridge; requires scanning QR on next login."""
        try:
            resp = requests.post(f"{WHATSAPP_API_URL}/logout", timeout=10, proxies={"http": None, "https": None})
            ok = False; msg = ""
            try:
                data = resp.json(); ok = data.get("success", False); msg = data.get("message", "")
            except Exception:
                msg = resp.text
            await update.message.reply_text("✅ Logged out. QR will be required next login." if ok else f"❌ Logout failed: {msg}")
        except Exception as e:
            await update.message.reply_text(f"❌ Logout error: {e}")

    async def cmd_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Trigger bridge login; QR will be generated and sent to Telegram."""
        try:
            resp = requests.post(f"{WHATSAPP_API_URL}/login", timeout=10, proxies={"http": None, "https": None})
            ok = False; msg = ""
            try:
                data = resp.json(); ok = data.get("success", False); msg = data.get("message", "")
            except Exception:
                msg = resp.text
            await update.message.reply_text("✅ Login started. Check Telegram for QR." if ok else f"❌ Login failed: {msg}")
        except Exception as e:
            await update.message.reply_text(f"❌ Login error: {e}")
    
    async def cmd_queue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show queue summary."""
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(1) FROM queue_items WHERE status='pending'")
            pending = cur.fetchone()[0]
            cur.execute("SELECT message_id, sender_name, created_at FROM queue_items WHERE status='pending' ORDER BY created_at ASC LIMIT 5")
            rows = cur.fetchall(); conn.close()
            lines = [f"🗂️ Pending: {pending}"]
            for mid, sname, created in rows:
                lines.append(f"• {sname} — {created}")
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"❌ Error reading queue: {e}")

    async def cmd_next(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Advance to next pending item (defer current active)."""
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute("SELECT id FROM queue_items WHERE status='active' ORDER BY id DESC LIMIT 1")
            r = cur.fetchone()
            if r:
                cur.execute("UPDATE queue_items SET status='pending', last_transition_at=CURRENT_TIMESTAMP WHERE id=?", (r[0],))
                conn.commit()
            conn.close()
        except Exception as e:
            await update.message.reply_text(f"❌ Error advancing: {e}")
            return
        nxt = self.activate_next_pending()
        if nxt:
            await self.present_active_item(nxt)
            await update.message.reply_text("➡️ Moved to next message.")
        else:
            await update.message.reply_text("✅ Queue is empty.")

    async def run(self):
        """Main run method"""
        print("🚀 Starting WhatsApp AI Bot...\n", flush=True)

        # Initialize the application
        await self.telegram_app.initialize()
        print("✅ Telegram app initialized", flush=True)

        # Start the application
        await self.telegram_app.start()
        print("✅ Telegram app started", flush=True)

        # Start polling for updates
        await self.telegram_app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False
        )
        print("✅ Telegram polling started", flush=True)
        print(f"✅ Bot is ready! Chat ID: {YOUR_TELEGRAM_CHAT_ID}\n", flush=True)

        # Start WhatsApp message processing
        try:
            # Present any existing active/pending item on startup
            try:
                item = self.get_active_item()
                if not item:
                    item = self.activate_next_pending()
                if item:
                    await self.present_active_item(item)
            except Exception as e:
                print(f"Startup present failed: {e}", flush=True)

            await self.process_messages()
        finally:
            # Cleanup
            await self.telegram_app.updater.stop()
            await self.telegram_app.stop()
            await self.telegram_app.shutdown()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  WhatsApp AI Bot with Telegram Integration")
    print("=" * 60 + "\n")

    bot = WhatsAppAIBot()
    asyncio.run(bot.run())