import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# WhatsApp Bridge API
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "http://localhost:8080/api")

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4")

# OpenAI Assistants API Configuration (optional - for thread-based conversations)
# Set to "assistants" to use Assistants API, or "chat" (default) for Chat Completions
OPENAI_API_MODE = os.getenv("OPENAI_API_MODE", "chat")  # "chat" or "assistants"
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID", None)  # Required if using Assistants API

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
    (
        "You are a clinical-style medical assistant. Provide practical, step-by-step guidance based on the "
        "user's symptoms using evidence-informed best practices. Do not reflexively tell the user to seek "
        "medical help; reserve escalation for clear red flags or emergencies, which you must explicitly list. "
        "Otherwise, act as the medical help: give at-home management, what to monitor, dosing ranges when "
        "appropriate, differential considerations, and when to escalate if symptoms worsen. Be concise and "
        "actionable. If critical information is missing, ask 3–5 targeted questions first. Include a brief line: "
        "'This is informational support, not a diagnosis.'"
    ),
)

# Whisper Transcription Settings
# Language codes: "ar" (Arabic), "en" (English), None (auto-detect)
# For mixed languages, use None for auto-detection
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "ar")  # Default to Arabic
