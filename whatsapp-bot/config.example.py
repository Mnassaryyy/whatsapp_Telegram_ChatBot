# Configuration file for WhatsApp AI Bot
# Copy this file to config.py and fill in your values

# WhatsApp Bridge API
WHATSAPP_API_URL = "http://localhost:8080/api"

# OpenAI Configuration
OPENAI_API_KEY = "sk-proj-YOUR_OPENAI_API_KEY_HERE"
OPENAI_MODEL = "gpt-4"  # or "gpt-3.5-turbo" for cheaper option

# Telegram Configuration
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
YOUR_TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID_HERE"

# Google Sheets Configuration
GOOGLE_SHEETS_CREDENTIALS_FILE = "credentials.json"
GOOGLE_SHEET_ID = "YOUR_GOOGLE_SHEET_ID_HERE"
SHEET_NAME = "WhatsApp Messages"

# Database Configuration
DATABASE_PATH = "../whatsapp-bridge/store/messages.db"

# Bot Settings
POLL_INTERVAL = 2  # Check for new messages every 2 seconds
MAX_CONVERSATION_HISTORY = 10  # Number of previous messages to include in AI context

