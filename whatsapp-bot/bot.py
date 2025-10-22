# bot.py
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

import sqlite3
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
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_approve, pattern=r"^approve_"))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_record_own, pattern=r"^record_"))
        self.telegram_app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))

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
                  AND (m.content != '' OR m.media_type = 'audio')
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
            {"role": "system",
             "content": "You are a helpful WhatsApp assistant. Respond naturally and conversationally."}
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
            print(f"❌ No approval found for message_id: {message_id}", flush=True)
            print(f"Available approvals: {list(self.pending_approvals.keys())}", flush=True)
            await query.edit_message_text("⚠️ This request has expired or was already processed.")
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

                # Update Telegram message
                await query.edit_message_text(
                    f"✅ *Message Approved & Sent!*\n\n"
                    f"Sent to: {approval['sender_id']}\n"
                    f"Reply: {approval['ai_reply']}",
                    parse_mode='Markdown'
                )

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
            else:
                await update.message.reply_text("❌ Failed to send voice message. Check WhatsApp bridge.")

            del context.user_data['pending_voice']

        except Exception as e:
            print(f"Error sending voice: {e}", flush=True)
            await update.message.reply_text(f"❌ Error: {str(e)}")
            del context.user_data['pending_voice']

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

                    # Handle voice messages
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

                    print(f"\n📨 Processing message from {sender_name or sender}: {content}", flush=True)

                    # Generate AI reply
                    ai_reply = self.generate_ai_reply(sender_jid, content)
                    print(f"🤖 AI Reply: {ai_reply}", flush=True)

                    # Log to Google Sheets
                    row_number = self.log_to_sheets(
                        timestamp, sender_jid, sender_name, content, ai_reply
                    )

                    # Store row number for later update
                    self.pending_approvals[msg_id] = {
                        'sender_id': sender_jid,
                        'ai_reply': ai_reply,
                        'row_number': row_number
                    }

                    print(f"📋 Stored approval with ID: {msg_id}", flush=True)

                    # Send Telegram notification
                    await self.send_telegram_notification(
                        sender_name, sender_jid, content, ai_reply, msg_id, is_voice
                    )

                    print(f"✅ Telegram notification sent\n", flush=True)

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