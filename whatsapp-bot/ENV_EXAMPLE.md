# Environment Variables - Example Configuration

Copy these to your `config.py` file with your actual values.

## OpenAI API
```
OPENAI_API_KEY = "sk-proj-YOUR_KEY_HERE"
OPENAI_MODEL = "gpt-4"  # or "gpt-3.5-turbo"
```
Get from: https://platform.openai.com/api-keys

## Telegram Bot
```
TELEGRAM_BOT_TOKEN = "1234567890:ABCdefGHIjkl..."
YOUR_TELEGRAM_CHAT_ID = "123456789"
```
- Bot token from: @BotFather on Telegram
- Chat ID from: @userinfobot on Telegram

## Google Sheets
```
GOOGLE_SHEET_ID = "your-sheet-id-here"
SHEET_NAME = "WhatsApp Messages"
GOOGLE_SHEETS_CREDENTIALS_FILE = "credentials.json"
```
Sheet ID from URL: `docs.google.com/spreadsheets/d/[THIS_PART]/edit`

## WhatsApp Bridge
```
WHATSAPP_API_URL = "http://localhost:8080/api"
DATABASE_PATH = "../whatsapp-bridge/store/messages.db"
```

## Bot Settings
```
POLL_INTERVAL = 2
MAX_CONVERSATION_HISTORY = 10
```

