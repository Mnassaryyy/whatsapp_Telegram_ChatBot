# WhatsApp AI Bot - Setup Guide

## 📋 Prerequisites Checklist

### 1. **OpenAI API Key**
- Go to: https://platform.openai.com/api-keys
- Click "Create new secret key"
- Copy the key (starts with `sk-...`)
- Paste in `config.py` → `OPENAI_API_KEY`

### 2. **Telegram Bot Token**
1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Follow prompts to create your bot
4. Copy the token (format: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)
5. Paste in `config.py` → `TELEGRAM_BOT_TOKEN`

### 3. **Your Telegram Chat ID**
1. Search for `@userinfobot` on Telegram
2. Start the bot
3. Copy your ID (number only)
4. Paste in `config.py` → `YOUR_TELEGRAM_CHAT_ID`

### 4. **Google Sheets API**

#### Step 1: Create Google Cloud Project
1. Go to: https://console.cloud.google.com/
2. Create new project
3. Enable Google Sheets API:
   - Go to "APIs & Services" → "Library"
   - Search "Google Sheets API"
   - Click "Enable"

#### Step 2: Create Service Account
1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "Service Account"
3. Fill in details and create
4. Click on the service account
5. Go to "Keys" tab
6. "Add Key" → "Create new key" → "JSON"
7. Download the JSON file
8. Rename it to `credentials.json`
9. Move it to `whatsapp-bot/` folder

#### Step 3: Create Google Sheet
1. Go to: https://sheets.google.com/
2. Create new spreadsheet
3. Name it "WhatsApp Messages" (or anything)
4. Copy the Sheet ID from URL:
   - URL: `https://docs.google.com/spreadsheets/d/SHEET_ID_HERE/edit`
   - Paste in `config.py` → `GOOGLE_SHEET_ID`
5. Share the sheet with service account email:
   - Open the `credentials.json` file
   - Find `client_email` value
   - Share your Google Sheet with this email (Editor access)

## 🚀 Installation Steps

### 1. Install Python Dependencies
```bash
cd whatsapp-mcp/whatsapp-bot
pip install -r requirements.txt
```

### 2. Configure Settings
Edit `config.py` and fill in:
- `OPENAI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `YOUR_TELEGRAM_CHAT_ID`
- `GOOGLE_SHEET_ID`

### 3. Start WhatsApp Bridge
```bash
cd ../whatsapp-bridge
go run main.go
```
Leave this running in a separate terminal.

### 4. Start the Bot
```bash
cd ../whatsapp-bot
python bot.py
```

## ✅ Testing

1. Send a message to your WhatsApp number from another phone
2. Check your Telegram - you should receive:
   - The incoming message
   - AI suggested reply
   - Approval buttons
3. Check Google Sheets - message should be logged
4. Click "✅ Approve & Send" or "🎤 Record Own"
5. Reply gets sent to WhatsApp!

## 🔧 Troubleshooting

### "Failed to send message"
- Check WhatsApp bridge is running on port 8080
- Verify with: `curl http://localhost:8080`

### "Google Sheets error"
- Verify `credentials.json` exists
- Check service account email has access to sheet
- Confirm `GOOGLE_SHEET_ID` is correct

### "Telegram not receiving"
- Verify bot token is correct
- Check your Telegram chat ID
- Make sure you've started the bot (`/start` command)

### "AI not generating replies"
- Check OpenAI API key is valid
- Ensure you have credits in OpenAI account
- Try `gpt-3.5-turbo` if `gpt-4` doesn't work

## 📊 Google Sheets Columns

| Column | Description |
|--------|-------------|
| Timestamp | When message was received |
| Sender ID | WhatsApp JID (unique ID) |
| Sender Name | Contact name |
| Incoming Message | What they sent you |
| AI Reply | What GPT suggested |
| Status | Pending/Sent (AI)/Sent (Manual Voice) |
| Final Reply Sent | Actual reply that was sent |

## 🎯 Next Steps

After everything works:
1. Set up hosting (VPS/Cloud)
2. Configure auto-start on boot
3. Add error notifications
4. Customize AI personality in `generate_ai_reply()`



