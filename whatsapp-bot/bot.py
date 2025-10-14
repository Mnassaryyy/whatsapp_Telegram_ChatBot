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
        
        query = """
            SELECT m.id, m.chat_jid, m.sender, m.content, m.timestamp, c.name
            FROM messages m
            LEFT JOIN chats c ON m.chat_jid = c.jid
            WHERE m.timestamp > ? 
            AND m.is_from_me = 0
            AND m.content != ''
            ORDER BY m.timestamp ASC
        """
        
        cursor.execute(query, (self.last_processed_timestamp,))
        messages = cursor.fetchall()
        conn.close()
        
        return messages
    
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
    async def send_telegram_notification(self, sender_name, sender_id, incoming_msg, ai_reply, message_id):
        """Send notification to Telegram with approval buttons"""
        text = f"""🔔 *New WhatsApp Message*
        
👤 *From:* {sender_name or sender_id}
📱 *Number:* {sender_id}

💬 *Message:*
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
        await query.answer()
        
        message_id = query.data.replace("approve_", "")
        
        if message_id not in self.pending_approvals:
            await query.edit_message_text("❌ This request has expired.")
            return
        
        approval = self.pending_approvals[message_id]
        
        # Send AI reply to WhatsApp
        success = self.send_whatsapp_message(approval['sender_id'], approval['ai_reply'])
        
        if success:
            # Update Google Sheets
            self.update_sheet_status(approval['row_number'], "Sent (AI)", approval['ai_reply'])
            await query.edit_message_text(f"✅ *AI Reply Sent Successfully!*\n\nReply: {approval['ai_reply']}", parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ Failed to send message. Check WhatsApp bridge.")
        
        del self.pending_approvals[message_id]
    
    async def handle_record_own(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle record own reply button"""
        query = update.callback_query
        await query.answer()
        
        message_id = query.data.replace("record_", "")
        
        if message_id not in self.pending_approvals:
            await query.edit_message_text("❌ This request has expired.")
            return
        
        # Store context for voice handler
        context.user_data['pending_voice'] = message_id
        
        await query.edit_message_text("🎤 *Send your voice message now...*", parse_mode='Markdown')
    
    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voice message from user"""
        if 'pending_voice' not in context.user_data:
            return
        
        message_id = context.user_data['pending_voice']
        approval = self.pending_approvals.get(message_id)
        
        if not approval:
            await update.message.reply_text("❌ Request expired.")
            return
        
        # Download voice message
        voice = update.message.voice
        file = await voice.get_file()
        voice_path = f"voice_{message_id}.ogg"
        await file.download_to_drive(voice_path)
        
        # Send voice to WhatsApp
        success = self.send_whatsapp_voice(approval['sender_id'], voice_path)
        
        if success:
            self.update_sheet_status(approval['row_number'], "Sent (Manual Voice)", "[Voice Message]")
            await update.message.reply_text("✅ *Voice message sent successfully!*", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Failed to send voice message.")
        
        del self.pending_approvals[message_id]
        del context.user_data['pending_voice']
    
    # ==================== WhatsApp API Functions ====================
    def send_whatsapp_message(self, recipient, message):
        """Send text message to WhatsApp"""
        try:
            response = requests.post(
                f"{WHATSAPP_API_URL}/send",
                json={
                    "recipient": recipient,
                    "message": message
                }
            )
            return response.json().get('success', False)
        except Exception as e:
            print(f"Error sending WhatsApp message: {e}")
            return False
    
    def send_whatsapp_voice(self, recipient, voice_path):
        """Send voice message to WhatsApp"""
        try:
            response = requests.post(
                f"{WHATSAPP_API_URL}/send",
                json={
                    "recipient": recipient,
                    "message": "",
                    "media_path": voice_path
                }
            )
            return response.json().get('success', False)
        except Exception as e:
            print(f"Error sending WhatsApp voice: {e}")
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
                
                for msg_id, sender_jid, sender, content, timestamp, sender_name in new_messages:
                    print(f"Processing message from {sender_name or sender}: {content}")
                    
                    # Update last processed timestamp
                    self.last_processed_timestamp = timestamp
                    
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
                        sender_name, sender_jid, content, ai_reply, msg_id
                    )
                
                # Sleep before next check
                await asyncio.sleep(POLL_INTERVAL)
                
            except Exception as e:
                print(f"Error in main loop: {e}")
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
        print("🚀 WhatsApp AI Bot started!")
        self.telegram_app.run_polling()

if __name__ == "__main__":
    bot = WhatsAppAIBot()
    bot.run()



