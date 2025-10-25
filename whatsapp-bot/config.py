import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# WhatsApp Bridge API
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "http://localhost:8080/api")

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4")

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YOUR_TELEGRAM_CHAT_ID = os.getenv("YOUR_TELEGRAM_CHAT_ID")

# Google Sheets Configuration
GOOGLE_SHEETS_CREDENTIALS_FILE = os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "credentials.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "WhatsApp Messages")

# Database Configuration
DATABASE_PATH = os.getenv("DATABASE_PATH", "../whatsapp-bridge/store/messages.db")

# Bot Settings
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "2"))
MAX_CONVERSATION_HISTORY = int(os.getenv("MAX_CONVERSATION_HISTORY", "10"))
AI_SYSTEM_PROMPT = os.getenv(
    "AI_SYSTEM_PROMPT",
    "You are a helpful WhatsApp assistant. Respond naturally and conversationally.",
)

# Whisper Transcription Settings
# Language codes: "ar" (Arabic), "en" (English), None (auto-detect)
# For mixed languages, use None for auto-detection
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "ar")  # Default to Arabic
