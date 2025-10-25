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
import logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO  # Changed to INFO to reduce noise
)


class WhatsAppAIBot:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.last_processed_timestamp = datetime.now()
        self.pending_approvals = {}  # Store pending AI replies
        self.processed_message_ids = set()  # Track processed message IDs to avoid duplicates
        self.first_card_sent = False  # Controls timestamp wording on first presented item
        
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
        self.telegram_app = (
            Application
            .builder()
            .token(TELEGRAM_BOT_TOKEN)
            .build()
        )

        # Register handlers - Order matters!
        self.telegram_app.add_handler(CommandHandler("start", self.start_command))
        self.telegram_app.add_handler(CommandHandler("queue", self.cmd_queue))
        self.telegram_app.add_handler(CommandHandler("next", self.cmd_next))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_approve, pattern=r"^approve_"))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_record_own, pattern=r"^record_"))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_reject, pattern=r"^reject_"))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_reply_later, pattern=r"^later_"))
        self.telegram_app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))

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
    
    # ==================== PHASE 1: Message Detection ====================
    def get_new_messages(self):
        """Monitor database for new messages"""
        conn = sqlite3.connect(DATABASE_PATH)
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
                ORDER BY m.timestamp ASC \
        """
        
        cursor.execute(query, (timestamp_str,))
        messages = cursor.fetchall()
        conn.close()
        
        return messages
    
    def transcribe_voice_message(self, message_id, chat_jid):
        """Download and transcribe voice message"""
        try:
            # Download the audio file using WhatsApp API
            response = requests.post(
                f"{WHATSAPP_API_URL}/download",
                json={
                    "message_id": message_id,
                    "chat_jid": chat_jid
                }
            )
            
            result = response.json()
            if not result.get('success'):
                return None
            
            audio_path = result.get('path')
            if not audio_path:
                return None
            
            # Transcribe using OpenAI Whisper with multi-language support
            with open(audio_path, 'rb') as audio_file:
                # Use configured language or auto-detect
                lang = WHISPER_LANGUAGE if WHISPER_LANGUAGE and WHISPER_LANGUAGE.lower() != "none" else None
                
                if lang:
                    transcription = self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language=lang,
                        response_format="text"
                    )
                else:
                    # Auto-detect language
                    transcription = self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        response_format="text"
                    )
            
            return transcription
            
        except Exception as e:
            print(f"Error transcribing voice: {e}", flush=True)
            return None
    
    # ==================== PHASE 2: AI Reply Generation ====================
    def generate_ai_reply(self, sender_jid, message_text):
        """Generate AI reply using GPT with conversation context"""
        # Get conversation history
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT content, is_from_me, timestamp 
            FROM messages 
            WHERE chat_jid = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (sender_jid, MAX_CONVERSATION_HISTORY))
        
        history = cursor.fetchall()
        conn.close()
        
        # Build conversation context
        context_messages = [
            {"role": "system", "content": AI_SYSTEM_PROMPT}
        ]
        
        for msg_content, is_from_me, _ in reversed(history):
            role = "assistant" if is_from_me else "user"
            context_messages.append({"role": role, "content": msg_content})
        
        # Generate reply
        response = self.client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=context_messages
        )
        
        return response.choices[0].message.content
    
    # ==================== Media Download & Telegram Send ====================
    def download_media(self, message_id, chat_jid):
        """Ask bridge to download media and return (ok, media_type, filename, abs_path)."""
        try:
            url = f"{WHATSAPP_API_URL}/download"
            resp = requests.post(
                url,
                json={"message_id": message_id, "chat_jid": chat_jid},
                timeout=12,
                proxies={"http": None, "https": None},
            )
            data = resp.json()
            if not data.get("success"):
                return False, "", "", ""
            # Bridge returns: Success, Message, Filename, Path
            return True, data.get("Message", ""), data.get("Filename", ""), data.get("Path", "")
        except Exception as e:
            print(f"Error downloading media: {e}", flush=True)
            return False, "", "", ""

    async def send_telegram_media(self, media_type, media_path, caption):
        """Send media preview to Telegram chat with best matching method."""
        try:
            if not os.path.isabs(media_path):
                media_path = os.path.abspath(media_path)
            if not os.path.exists(media_path):
                print(f"Media path not found: {media_path}", flush=True)
                return

            if media_type == "image":
                with open(media_path, "rb") as f:
                    await self.telegram_app.bot.send_photo(chat_id=YOUR_TELEGRAM_CHAT_ID, photo=f, caption=caption)
            elif media_type == "video":
                with open(media_path, "rb") as f:
                    await self.telegram_app.bot.send_video(chat_id=YOUR_TELEGRAM_CHAT_ID, video=f, caption=caption)
            else:
                # document or other
                with open(media_path, "rb") as f:
                    await self.telegram_app.bot.send_document(chat_id=YOUR_TELEGRAM_CHAT_ID, document=f, caption=caption)
        except Exception as e:
            print(f"Error sending media preview to Telegram: {e}", flush=True)

    def find_recent_media_in_store(self, chat_jid: str) -> str:
        """Heuristic fallback: pick the most recent file under bridge store/<chat_jid>."""
        try:
            base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "whatsapp-bridge", "store", chat_jid))
            if not os.path.isdir(base):
                return ""
            latest_path = ""; latest_mtime = 0
            for root, _, files in os.walk(base):
                for name in files:
                    p = os.path.join(root, name)
                    try:
                        m = os.path.getmtime(p)
                        if m > latest_mtime:
                            latest_mtime = m; latest_path = p
                    except Exception:
                        pass
            return latest_path
        except Exception:
            return ""

    def get_media_size_bytes(self, message_id: str, chat_jid: str) -> int:
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute("SELECT file_length FROM messages WHERE id=? AND chat_jid=?", (message_id, chat_jid))
            r = cur.fetchone(); conn.close()
            if r and r[0]:
                return int(r[0])
        except Exception:
            pass
        return 0

    def format_size(self, num_bytes: int) -> str:
        units = ["B", "KB", "MB", "GB"]
        size = float(num_bytes)
        i = 0
        while size >= 1024 and i < len(units)-1:
            size /= 1024.0
            i += 1
        return f"{size:.1f} {units[i]}" if num_bytes > 0 else "unknown"

    # ==================== Queue Helpers ====================
    def is_greeting(self, text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        keywords = ("hi", "hello", "hey", "assalam", "good morning", "good evening", "good night", "salam")
        return any(k in t for k in keywords) and len(t) <= 30

    def enqueue_item(self, message_id, chat_jid, sender_name, content, media_type, media_path, ai_reply, row_number):
        priority = 50 if self.is_greeting(content or "") else 20
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO queue_items (message_id, chat_jid, sender_name, content, media_type, media_path, ai_reply, row_number, status, priority, last_transition_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
                """,
                (message_id, chat_jid, sender_name or chat_jid, content or "", media_type or "", media_path or "", ai_reply or "", row_number or 0, priority),
            )
            conn.commit(); conn.close()
        except Exception as e:
            print(f"Failed to enqueue item: {e}", flush=True)

    def get_active_item(self):
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute("SELECT id, message_id, chat_jid, sender_name, content, media_type, media_path, ai_reply, row_number FROM queue_items WHERE status='active' ORDER BY id LIMIT 1")
            row = cur.fetchone(); conn.close()
            return row
        except Exception as e:
            print(f"Failed to load active item: {e}", flush=True)
            return None

    def activate_next_pending(self):
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute("SELECT id FROM queue_items WHERE status='pending' ORDER BY priority ASC, created_at ASC LIMIT 1")
            row = cur.fetchone()
            if not row:
                conn.close(); return None
            qid = row[0]
            cur.execute("UPDATE queue_items SET status='active', last_transition_at=CURRENT_TIMESTAMP WHERE id=?", (qid,))
            conn.commit()
            cur.execute("SELECT id, message_id, chat_jid, sender_name, content, media_type, media_path, ai_reply, row_number FROM queue_items WHERE id=?", (qid,))
            item = cur.fetchone(); conn.close(); return item
        except Exception as e:
            print(f"Failed to activate next pending: {e}", flush=True)
            return None

    def mark_item_status(self, qid: int, status: str):
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute("UPDATE queue_items SET status=?, last_transition_at=CURRENT_TIMESTAMP WHERE id=?", (status, qid))
            conn.commit(); conn.close()
        except Exception as e:
            print(f"Failed to set status {status} on {qid}: {e}", flush=True)

    def pending_count(self) -> int:
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor(); cur.execute("SELECT COUNT(1) FROM queue_items WHERE status='pending'")
            n = cur.fetchone()[0]; conn.close(); return int(n)
        except Exception:
            return 0

    async def safe_edit(self, query, text, parse_mode=None):
        """Edit a message card that might be text or media with caption."""
        try:
            msg = query.message
            if msg and (getattr(msg, 'photo', None) or getattr(msg, 'video', None) or getattr(msg, 'document', None)):
                await query.edit_message_caption(caption=text, parse_mode=parse_mode)
            else:
                await query.edit_message_text(text, parse_mode=parse_mode)
        except Exception as e:
            print(f"safe_edit failed: {e}", flush=True)

    async def present_active_item(self, item):
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
        keyboard = [[
            InlineKeyboardButton("✅ Approve & Send", callback_data=f"approve_{msg_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{msg_id}"),
        ],[
            InlineKeyboardButton("🎤 Record Own", callback_data=f"record_{msg_id}"),
            InlineKeyboardButton("🕓 Reply Later", callback_data=f"later_{msg_id}")
        ]]
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
                await self.telegram_app.bot.send_message(chat_id=YOUR_TELEGRAM_CHAT_ID, text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except Exception as e:
            print(f"Failed to send approval card: {e}", flush=True)
        # After first present, switch to relative wording for subsequent items
        self.first_card_sent = True
    
    # ==================== PHASE 3: Google Sheets Logging ====================
    def log_to_sheets(self, timestamp, sender_id, sender_name, incoming_msg, ai_reply, status="Pending",
                      final_reply=""):
        """Log message and AI reply to Google Sheets"""
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
        """Send notification to Telegram with approval buttons"""
        message_type = "🎤 *Voice Message (Transcribed)*" if is_voice else "💬 *Message:*"
        
        text = f"""🔔 *New WhatsApp Message*
        
👤 *From:* {sender_name or sender_id}
📱 *Number:* {sender_id}

{message_type}
{incoming_msg}

🤖 *AI Suggested Reply:*
{ai_reply}
"""
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve & Send", callback_data=f"approve_{message_id}"),
                InlineKeyboardButton("🎤 Record Own", callback_data=f"record_{message_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
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
        """Handle approval button click"""
        query = update.callback_query
        await query.answer()  # Acknowledge the button click
        
        # Extract message_id from callback data
        message_id = query.data.replace("approve_", "")
        print(f"\n{'=' * 60}", flush=True)
        print(f"[APPROVE BUTTON CLICKED]", flush=True)
        print(f"Message ID: {message_id}", flush=True)
        print(f"{'=' * 60}\n", flush=True)

        # Get pending approval data
        approval = self.pending_approvals.get(message_id)

        if not approval:
            # Try to recover from persistent queue (e.g., after a restart)
            try:
                conn = sqlite3.connect(DATABASE_PATH)
                cur = conn.cursor()
                cur.execute(
                    "SELECT chat_jid, ai_reply, row_number FROM queue_items WHERE message_id=? ORDER BY last_transition_at DESC, id DESC LIMIT 1",
                    (message_id,),
                )
                r = cur.fetchone(); conn.close()
                if r:
                    approval = { 'sender_id': r[0], 'ai_reply': r[1], 'row_number': r[2] }
                    self.pending_approvals[message_id] = approval
            except Exception as e:
                print(f"Recovery lookup failed: {e}", flush=True)

        if not approval:
            print(f"❌ No approval found for message_id: {message_id}", flush=True)
            print(f"Available approvals: {list(self.pending_approvals.keys())}", flush=True)
            await query.edit_message_text("⚠️ This request has expired or was already processed.")
            # Free any stuck active queue item for this message and advance
            try:
                conn = sqlite3.connect(DATABASE_PATH)
                cur = conn.cursor()
                cur.execute("UPDATE queue_items SET status='pending', last_transition_at=CURRENT_TIMESTAMP WHERE status='active' AND message_id=?", (message_id,))
                conn.commit(); conn.close()
            except Exception as e:
                print(f"Queue reset on expired failed: {e}", flush=True)
            nxt = self.activate_next_pending()
            if nxt:
                await self.present_active_item(nxt)
            return
        
        try:
            # Send the AI reply to WhatsApp
            print(f"📤 Sending to WhatsApp...", flush=True)
            print(f"   Recipient: {approval['sender_id']}", flush=True)
            print(f"   Message: {approval['ai_reply']}", flush=True)

        success = self.send_whatsapp_message(approval['sender_id'], approval['ai_reply'])
        
        if success:
                print(f"✅ WhatsApp message sent successfully!", flush=True)

                # Update Google Sheets status
                if approval.get('row_number'):
                    self.update_sheet_status(
                        approval['row_number'],
                        "Sent (AI Reply)",
                        approval['ai_reply']
                    )
                    print(f"📊 Google Sheets updated (Row {approval['row_number']})", flush=True)

                # Update Telegram message (text or media caption)
                await self.safe_edit(
                    query,
                    f"✅ *Message Approved & Sent!*\n\n"
                    f"Sent to: {approval['sender_id']}\n"
                    f"Reply: {approval['ai_reply']}",
                    parse_mode='Markdown'
                )
                # mark queue done and present next
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
                print(f"❌ Failed to send WhatsApp message", flush=True)
                await query.edit_message_text(
                    "❌ *Failed to send message to WhatsApp.*\n\n"
                    "Please check:\n"
                    "- WhatsApp bridge is running\n"
                    "- API endpoint is correct\n"
                    "- Network connection",
                    parse_mode='Markdown'
                )

        except Exception as e:
            print(f"❌ Error in handle_approve: {e}", flush=True)
            import traceback
            traceback.print_exc()
            await query.edit_message_text(f"❌ Error: {str(e)}")
    
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
        """Handle voice message from user"""
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
        try:
            print(f"\n[SEND_WHATSAPP_MESSAGE]", flush=True)
            print(f"  URL: {WHATSAPP_API_URL}/send", flush=True)
            print(f"  Recipient: {recipient}", flush=True)
            print(f"  Message: {message}", flush=True)

            resp = requests.post(
                f"{WHATSAPP_API_URL}/send",
                json={
                    "recipient": recipient,
                    "message": message
                },
                timeout=10
            )

            print(f"  Status Code: {resp.status_code}", flush=True)
            print(f"  Response: {resp.text}", flush=True)

            j = resp.json()
            success = j.get("success", False)
            print(f"  Success: {success}", flush=True)
            return success

        except Exception as e:
            print(f"❌ Error sending WhatsApp message: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return False
    
    def send_whatsapp_voice(self, recipient, voice_path):
        """Send voice message to WhatsApp"""
        try:
            print(f"Sending voice to {recipient} from {voice_path}", flush=True)
            response = requests.post(
                f"{WHATSAPP_API_URL}/send",
                json={
                    "recipient": recipient,
                    "message": "",
                    "media_path": voice_path
                },
                timeout=10
            )
            result = response.json()
            print(f"WhatsApp API response: {result}", flush=True)
            return result.get('success', False)
        except Exception as e:
            print(f"Error sending WhatsApp voice: {e}", flush=True)
            return False
    
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

        while True:
            try:
                # Check for new messages
                new_messages = self.get_new_messages()
                # Enqueue all first, then present one active to ensure pending count reflects full batch
                enqueued_any = False
                active_before = self.get_active_item()
                
                for msg_id, sender_jid, sender, content, timestamp, sender_name, media_type in new_messages:
                    # Skip if already processed
                    if msg_id in self.processed_message_ids:
                        continue
                    
                    # Mark as processed
                    self.processed_message_ids.add(msg_id)
                    
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
                    
                    # Generate AI reply
                    ai_reply = self.generate_ai_reply(sender_jid, content)
                    print(f"🤖 AI Reply: {ai_reply}", flush=True)
                    
                    # Log to Google Sheets
                    row_number = self.log_to_sheets(timestamp, sender_jid, sender_name, content, ai_reply)
                    # Prepare media path for non-audio (reuse if already downloaded above)
                    media_path = locals().get('media_path_for_enqueue', "") if media_type in ("image", "video", "document") else ""
                    # Enqueue
                    self.enqueue_item(msg_id, sender_jid, sender_name, content, media_type, media_path, ai_reply, row_number)
                    enqueued_any = True

                # After enqueueing the batch, if nothing was active, present the next pending now
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