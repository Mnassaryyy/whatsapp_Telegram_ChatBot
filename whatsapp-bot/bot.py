import sqlite3
import requests
import time
import json
from datetime import datetime
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
import asyncio
from config import *

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
            self.sheet.append_row(['Timestamp', 'Sender ID', 'Sender Name', 'Incoming Message', 'AI Reply', 'Status', 'Final Reply Sent'])
    
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
            ORDER BY m.timestamp ASC
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
            {"role": "system", "content": "You are a helpful WhatsApp assistant. Respond naturally and conversationally."}
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
    def log_to_sheets(self, timestamp, sender_id, sender_name, incoming_msg, ai_reply, status="Pending", final_reply=""):
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
    async def send_telegram_notification(self, sender_name, sender_id, incoming_msg, ai_reply, message_id, is_voice=False):
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
        
        # Store pending approval
        self.pending_approvals[message_id] = {
            'sender_id': sender_id,
            'ai_reply': ai_reply,
            'row_number': None  # Will be set after sheets logging
        }
        
        return await self.telegram_app.bot.send_message(
            chat_id=YOUR_TELEGRAM_CHAT_ID,
            text=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    # ==================== PHASE 5: Approval System ====================
    async def handle_approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle approve button click"""
        query = update.callback_query
        try:
            await query.answer()
        except Exception as e:
            print(f"[DEBUG] query.answer() failed: {e}", flush=True)
            try:
                import traceback; traceback.print_exc()
            except Exception:
                pass
        
        message_id = query.data.replace("approve_", "")
        print(f"[DEBUG] Approve clicked for message_id={message_id}", flush=True)
        
        if message_id not in self.pending_approvals:
            print(f"[DEBUG] No pending approval found for message_id={message_id}", flush=True)
            await query.edit_message_text("❌ This request has expired or was already processed.")
            return
        
        approval = self.pending_approvals[message_id]
        print(
            f"[DEBUG] Sending AI reply via bridge: recipient={approval.get('sender_id')} "
            f"reply_len={len(approval.get('ai_reply',''))} api={WHATSAPP_API_URL}",
            flush=True,
        )
        
        # Send AI reply to WhatsApp
        success = self.send_whatsapp_message(approval['sender_id'], approval['ai_reply'])
        print(f"[DEBUG] Bridge send result success={success}", flush=True)
        
        if success:
            # Update Google Sheets
            try:
                self.update_sheet_status(approval['row_number'], "Sent (AI)", approval['ai_reply'])
            except Exception as e:
                print(f"[DEBUG] Sheets status update failed: {e}", flush=True)
                try:
                    import traceback; traceback.print_exc()
                except Exception:
                    pass
            try:
                await query.edit_message_text(
                    f"✅ *AI Reply Sent Successfully!*\n\nReply: {approval['ai_reply']}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"[DEBUG] Telegram edit_message_text failed: {e}", flush=True)
                try:
                    import traceback; traceback.print_exc()
                except Exception:
                    pass
            # Don't delete - keep for reference
            # del self.pending_approvals[message_id]
        else:
            try:
                await query.edit_message_text("❌ Failed to send message. Check WhatsApp bridge.")
            except Exception as e:
                print(f"[DEBUG] Telegram edit on failure failed: {e}", flush=True)
                try:
                    import traceback; traceback.print_exc()
                except Exception:
                    pass
    
    async def handle_record_own(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle record own reply button"""
        query = update.callback_query
        await query.answer()
        
        message_id = query.data.replace("record_", "")
        
        if message_id not in self.pending_approvals:
            await query.edit_message_text("❌ This request has expired or was already processed.")
            return
        
        # Store context for voice handler
        context.user_data['pending_voice'] = message_id
        
        await query.edit_message_text("🎤 *Send your voice message now...*\n\n_Send a voice note in this chat_", parse_mode='Markdown')
    
    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voice message from user"""
        print(f"Voice message received!", flush=True)
        
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
                # Don't delete - keep for reference
                # del self.pending_approvals[message_id]
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
            url = f"{WHATSAPP_API_URL}/send"
            payload = {"recipient": recipient, "message": message}
            print(f"[DEBUG] POST {url} payload_keys={list(payload.keys())}", flush=True)
            response = requests.post(
                url,
                json=payload,
                timeout=8,
                proxies={"http": None, "https": None},
            )
            print(
                f"[DEBUG] Bridge response status={response.status_code} "
                f"len={len(response.text) if hasattr(response,'text') else 'NA'}",
                flush=True,
            )
            try:
                data = response.json()
            except Exception as je:
                print(f"[DEBUG] JSON decode failed: {je}; body={response.text}", flush=True)
                return False
            print(f"[DEBUG] Bridge response json keys={list(data.keys())}", flush=True)
            return data.get('success', False)
        except Exception as e:
            print(f"Error sending WhatsApp message: {e}", flush=True)
            try:
                import traceback; traceback.print_exc()
            except Exception:
                pass
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
                timeout=15,
                proxies={"http": None, "https": None},
            )
            result = response.json()
            print(f"WhatsApp API response: {result}", flush=True)
            return result.get('success', False)
        except Exception as e:
            print(f"Error sending WhatsApp voice: {e}", flush=True)
            try:
                import traceback; traceback.print_exc()
            except Exception:
                pass
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
                    
                    print(f"Processing message from {sender_name or sender}: {content}", flush=True)
                    
                    # Generate AI reply
                    ai_reply = self.generate_ai_reply(sender_jid, content)
                    
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
                    
                    # Send Telegram notification
                    await self.send_telegram_notification(
                        sender_name, sender_jid, content, ai_reply, msg_id, is_voice
                    )
                
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
    
    def run(self):
        """Start the bot"""
        # Create Telegram application
        self.telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Add handlers
        self.telegram_app.add_handler(CommandHandler("start", self.start_command))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_approve, pattern="^approve_"))
        self.telegram_app.add_handler(CallbackQueryHandler(self.handle_record_own, pattern="^record_"))
        self.telegram_app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        
        # Start message processing loop
        loop = asyncio.get_event_loop()
        loop.create_task(self.process_messages())
        
        # Start Telegram bot
        print("🚀 WhatsApp AI Bot started!", flush=True)
        print("📱 Monitoring for new WhatsApp messages...", flush=True)
        print("💬 Send /start to your Telegram bot to verify connection", flush=True)
        self.telegram_app.run_polling()

if __name__ == "__main__":
    bot = WhatsAppAIBot()
    bot.run()



