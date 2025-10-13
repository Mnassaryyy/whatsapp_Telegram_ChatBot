# WhatsApp AI Assistant Bot

Automated WhatsApp assistant that uses AI to generate replies, sends them to your Telegram for approval, and logs everything to Google Sheets.

## 🎯 What It Does

1. **Monitors** your WhatsApp for incoming messages
2. **Generates** AI replies using GPT
3. **Sends** to your Telegram with:
   - The incoming message
   - AI suggested reply
   - Buttons to approve or record your own voice reply
4. **Logs** everything to Google Sheets
5. **Sends** approved reply back to WhatsApp

## 📁 Project Structure

```
whatsapp-mcp/
├── whatsapp-bridge/        # Go app - connects to WhatsApp
│   ├── main.go
│   └── store/              # SQLite databases
│       ├── whatsapp.db     # Session/auth
│       └── messages.db     # All messages
│
├── whatsapp-bot/           # Python bot - AI & automation
│   ├── bot.py              # Main bot logic
│   ├── config.py           # Configuration
│   ├── requirements.txt    # Dependencies
│   ├── credentials.json    # Google Sheets auth (you create this)
│   └── SETUP_GUIDE.md      # Detailed setup instructions
│
├── START_BOT.bat           # Easy start script (Windows)
└── README.md               # This file
```

## 🚀 Quick Start

### 1. **Install Dependencies**

   ```bash
# Install Python packages
cd whatsapp-bot
pip install -r requirements.txt
```

### 2. **Setup API Keys**

Follow the detailed guide: [`whatsapp-bot/SETUP_GUIDE.md`](whatsapp-bot/SETUP_GUIDE.md)

You'll need:
- ✅ OpenAI API Key
- ✅ Telegram Bot Token
- ✅ Your Telegram Chat ID
- ✅ Google Sheets credentials

### 3. **Configure**

Edit `whatsapp-bot/config.py` with your API keys.

### 4. **Run**

**Windows:**
```bash
# Double-click START_BOT.bat
# OR run manually:
```

**Manual start:**
```bash
# Terminal 1: Start WhatsApp Bridge
cd whatsapp-bridge
go run main.go

# Terminal 2: Start Bot
cd whatsapp-bot
python bot.py
```

## 📊 How It Works

### Flow:
```
WhatsApp Message → Detect → Generate AI Reply → Log to Sheets
                                    ↓
                            Send to Telegram
                                    ↓
                    [Approve Button] or [Record Voice Button]
                                    ↓
                            Send to WhatsApp
```

### Google Sheets Layout:
| Timestamp | Sender ID | Sender Name | Incoming Message | AI Reply | Status | Final Reply Sent |
|-----------|-----------|-------------|------------------|----------|--------|-----------------|
| 2025-01-14 15:30 | 880140... | John | Hey, how are you? | I'm doing great, thanks! | Sent (AI) | I'm doing great, thanks! |

## 🎛️ Customization

### Change AI Personality
Edit `whatsapp-bot/bot.py` → `generate_ai_reply()` function:
```python
{"role": "system", "content": "You are a helpful WhatsApp assistant..."}
```
Change to your preferred personality!

### Adjust Polling Interval
Edit `whatsapp-bot/config.py`:
```python
POLL_INTERVAL = 2  # Check every 2 seconds
```

### Use Different AI Model
Edit `whatsapp-bot/config.py`:
```python
OPENAI_MODEL = "gpt-3.5-turbo"  # Cheaper option
# or
OPENAI_MODEL = "gpt-4"  # Better responses
```

## 🔧 Troubleshooting

### WhatsApp Bridge Issues
```bash
# Check if running
curl http://localhost:8080

# Restart
   cd whatsapp-bridge
   go run main.go
   ```

### Bot Not Processing Messages
- Verify bridge is running
- Check `config.py` has correct `DATABASE_PATH`
- Look for errors in bot console

### Telegram Not Working
- Verify bot token with: https://api.telegram.org/bot<TOKEN>/getMe
- Check your chat ID is correct
- Make sure you started the bot with `/start`

## 📈 Next Steps

- [ ] Deploy to VPS for 24/7 uptime
- [ ] Add more AI customization
- [ ] Multi-language support
- [ ] Custom reply templates
- [ ] Analytics dashboard

## 🛡️ Security Notes

- **Never commit** `config.py` or `credentials.json` to Git
- **Keep** your API keys secret
- **Use** environment variables in production
- **Store** databases securely

## 📝 License

MIT License - Do whatever you want!
