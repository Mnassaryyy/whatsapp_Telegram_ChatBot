# 🚀 DigitalOcean Deployment Guide

Complete guide to deploy your WhatsApp AI Bot on DigitalOcean VPS.

---

## 📋 Step 1: Create a Droplet

1. **Login to DigitalOcean** → https://cloud.digitalocean.com/
2. Click **"Create"** → **"Droplets"**
3. **Choose Configuration:**
   - **Image:** Ubuntu 22.04 LTS
   - **Plan:** Basic ($6/month minimum recommended)
   - **CPU:** Regular (2GB RAM / 1 vCPU)
   - **Datacenter:** Choose closest to your location
   - **Authentication:** SSH Key (recommended) or Password
   - **Hostname:** `whatsapp-bot` (or your choice)
4. Click **"Create Droplet"**
5. Wait 1 minute for creation
6. **Copy your Droplet's IP address** (e.g., `123.45.67.89`)

---

## 📡 Step 2: Connect to Your Server

### Windows (PowerShell):
```powershell
ssh root@YOUR_DROPLET_IP
# Example: ssh root@123.45.67.89
```

### Mac/Linux:
```bash
ssh root@YOUR_DROPLET_IP
```

Type `yes` when asked about fingerprint, then enter your password.

---

## 🛠️ Step 3: Install Dependencies

Once connected, run these commands:

```bash
# Update system
apt update && apt upgrade -y

# Install Python 3 and pip
apt install -y python3 python3-pip python3-venv

# Install Go
wget https://go.dev/dl/go1.21.6.linux-amd64.tar.gz
tar -C /usr/local -xzf go1.21.6.linux-amd64.tar.gz
echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc
source ~/.bashrc

# Verify installations
python3 --version
go version

# Install Git
apt install -y git

# Install FFmpeg (for audio messages)
apt install -y ffmpeg

# Install screen (to keep processes running)
apt install -y screen
```

---

## 📦 Step 4: Clone Your Repository

```bash
# Clone your project
cd /root
git clone https://github.com/Mnassaryyy/whatsapp_Telegram_ChatBot.git
cd whatsapp_Telegram_ChatBot
```

---

## 🔐 Step 5: Setup Environment Variables

```bash
cd whatsapp-bot

# Create .env file
nano .env
```

**Paste your configuration:**
```env
# OpenAI Configuration
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-4o-mini

# Telegram Configuration
TELEGRAM_BOT_TOKEN=your-token-here
YOUR_TELEGRAM_CHAT_ID=your-chat-id-here

# Google Sheets Configuration
GOOGLE_SHEET_ID=your-sheet-id-here
SHEET_NAME=WhatsApp Messages
GOOGLE_SHEETS_CREDENTIALS_FILE=credentials.json

# WhatsApp Bridge Configuration
WHATSAPP_API_URL=http://localhost:8080/api
DATABASE_PATH=../whatsapp-bridge/store/messages.db

# Bot Settings
POLL_INTERVAL=2
MAX_CONVERSATION_HISTORY=10

# Whisper Transcription
WHISPER_LANGUAGE=ar
```

**Save:** Press `Ctrl+X`, then `Y`, then `Enter`

---

## 📄 Step 6: Upload Google Credentials

**On your local computer:**

```powershell
# Upload credentials.json to server
scp credentials.json root@YOUR_DROPLET_IP:/root/whatsapp_Telegram_ChatBot/whatsapp-bot/
```

Or use **FileZilla** / **WinSCP** to upload the file.

---

## 🐍 Step 7: Install Python Dependencies

```bash
cd /root/whatsapp_Telegram_ChatBot/whatsapp-bot
pip3 install -r requirements.txt
```

---

## 📱 Step 8: Start WhatsApp Bridge (First Time)

```bash
cd /root/whatsapp_Telegram_ChatBot/whatsapp-bridge
go run main.go
```

**You'll see a QR code!** 

📱 **Scan it with your WhatsApp:**
1. Open WhatsApp on your phone
2. Go to: **Settings → Linked Devices → Link a Device**
3. Scan the QR code from the terminal

Once connected, press `Ctrl+C` to stop (we'll run it properly next).

---

## 🚀 Step 9: Run Services with Screen

### Start WhatsApp Bridge:
```bash
cd /root/whatsapp_Telegram_ChatBot

# Create a screen session for WhatsApp Bridge
screen -S whatsapp-bridge
cd whatsapp-bridge
go run main.go
```

**Detach from screen:** Press `Ctrl+A` then `D`

### Start Python Bot:
```bash
# Create a screen session for Python Bot
screen -S whatsapp-bot
cd /root/whatsapp_Telegram_ChatBot/whatsapp-bot
python3 bot.py
```

**Detach from screen:** Press `Ctrl+A` then `D`

---

## 📊 Step 10: Manage Your Services

### View Running Sessions:
```bash
screen -ls
```

### Reattach to a Session:
```bash
# View WhatsApp Bridge logs
screen -r whatsapp-bridge

# View Python Bot logs
screen -r whatsapp-bot
```

**Detach again:** Press `Ctrl+A` then `D`

### Kill a Session:
```bash
screen -X -S whatsapp-bridge quit
screen -X -S whatsapp-bot quit
```

---

## 🔄 Step 11: Auto-Start on Reboot (Optional)

Create systemd services to auto-restart:

### WhatsApp Bridge Service:
```bash
nano /etc/systemd/system/whatsapp-bridge.service
```

**Paste:**
```ini
[Unit]
Description=WhatsApp Bridge
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/whatsapp_Telegram_ChatBot/whatsapp-bridge
ExecStart=/usr/local/go/bin/go run main.go
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Python Bot Service:
```bash
nano /etc/systemd/system/whatsapp-bot.service
```

**Paste:**
```ini
[Unit]
Description=WhatsApp AI Bot
After=network.target whatsapp-bridge.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/whatsapp_Telegram_ChatBot/whatsapp-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Enable Services:
```bash
systemctl daemon-reload
systemctl enable whatsapp-bridge
systemctl enable whatsapp-bot
systemctl start whatsapp-bridge
systemctl start whatsapp-bot
```

### Check Status:
```bash
systemctl status whatsapp-bridge
systemctl status whatsapp-bot
```

### View Logs:
```bash
journalctl -u whatsapp-bridge -f
journalctl -u whatsapp-bot -f
```

---

## 🧪 Step 12: Test Your Bot

1. Send a WhatsApp message to your number
2. Check your Telegram - you should get notification!
3. Click "Approve" or "Record Own"
4. Reply gets sent to WhatsApp!

---

## 🔒 Step 13: Security (Important!)

```bash
# Create a firewall
ufw allow OpenSSH
ufw enable

# Change SSH port (optional but recommended)
nano /etc/ssh/sshd_config
# Change Port 22 to Port 2222
systemctl restart sshd

# Then connect with: ssh -p 2222 root@YOUR_IP
```

---

## 🔧 Troubleshooting

### WhatsApp Bridge Won't Connect:
```bash
# Delete old session
cd /root/whatsapp_Telegram_ChatBot/whatsapp-bridge
rm -rf store/*.db
# Restart and scan QR again
```

### Python Bot Errors:
```bash
# Check logs
screen -r whatsapp-bot
# or
journalctl -u whatsapp-bot -f
```

### Update Your Code:
```bash
cd /root/whatsapp_Telegram_ChatBot
git pull
systemctl restart whatsapp-bridge
systemctl restart whatsapp-bot
```

---

## 📞 Quick Commands Reference

```bash
# SSH into server
ssh root@YOUR_DROPLET_IP

# View running processes
screen -ls

# Attach to WhatsApp Bridge
screen -r whatsapp-bridge

# Attach to Bot
screen -r whatsapp-bot

# Restart services
systemctl restart whatsapp-bridge
systemctl restart whatsapp-bot

# Check status
systemctl status whatsapp-bridge whatsapp-bot

# View logs
journalctl -u whatsapp-bot -f
```

---

## ✅ You're Live!

Your bot is now running 24/7 on DigitalOcean! 🎉

**Important Notes:**
- Keep your droplet running
- Monitor your OpenAI usage (costs money per API call)
- Backup your `.env` and `credentials.json` files
- Your WhatsApp session stays logged in ~20 days

---

## 💰 Cost Estimation

- **DigitalOcean Droplet:** $6-12/month
- **OpenAI GPT-4o-mini:** ~$0.15 per 1000 messages
- **Whisper Transcription:** ~$0.006 per minute of audio
- **Total:** ~$10-20/month for moderate use

---

Need help? Check the logs or contact support! 🚀

