# 🚀 WhatsApp AI Bot - Deployment Commands

Copy and paste these commands step by step. Your client will fill in their own credentials.

---

## **STEP 1: Connect to VPS**

**On Your Local Computer (PowerShell/Terminal):**
```powershell
ssh root@YOUR_VPS_IP
# Example: ssh root@64.227.62.89
```

When prompted:
- Type `yes` to accept fingerprint
- Enter the password from DigitalOcean email
- You'll be asked to change password - enter a new one

---

## **STEP 2: Install Dependencies**

**Run on the server (paste all at once):**
```bash
apt update && apt upgrade -y && \
apt install -y python3 python3-pip git ffmpeg screen wget && \
wget -q https://go.dev/dl/go1.21.6.linux-amd64.tar.gz && \
tar -C /usr/local -xzf go1.21.6.linux-amd64.tar.gz && \
export PATH=$PATH:/usr/local/go/bin && \
echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc && \
source ~/.bashrc && \
rm go1.21.6.linux-amd64.tar.gz && \
echo "✅ All dependencies installed!"
```

---

## **STEP 3: Clone Project**

```bash
cd /root && \
git clone https://github.com/Mnassaryyy/whatsapp_Telegram_ChatBot.git && \
cd whatsapp_Telegram_ChatBot && \
echo "✅ Project cloned!"
```

---

## **STEP 4: Create .env File**

```bash
cd whatsapp-bot
nano .env
```

**Paste this template and FILL IN the values:**
```env
# OpenAI Configuration
OPENAI_API_KEY=YOUR_OPENAI_API_KEY_HERE
OPENAI_MODEL=gpt-4o-mini

# Telegram Configuration  
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN_HERE
YOUR_TELEGRAM_CHAT_ID=YOUR_TELEGRAM_CHAT_ID_HERE

# Google Sheets Configuration
GOOGLE_SHEET_ID=YOUR_GOOGLE_SHEET_ID_HERE
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

**Save:**
- Press `Ctrl+X`
- Press `Y`
- Press `Enter`

---

## **STEP 5: Upload credentials.json**

**On Your Local Computer (NEW PowerShell window):**
```powershell
# Navigate to your project folder
cd E:\Mnassary\whatsapp-mcp

# Upload credentials.json to server
scp whatsapp-bot\credentials.json root@YOUR_VPS_IP:/root/whatsapp_Telegram_ChatBot/whatsapp-bot/
# Example: scp whatsapp-bot\credentials.json root@64.227.62.89:/root/whatsapp_Telegram_ChatBot/whatsapp-bot/
```

---

## **STEP 6: Install Python Packages**

**Back on the server:**
```bash
cd /root/whatsapp_Telegram_ChatBot/whatsapp-bot && \
pip3 install -r requirements.txt && \
echo "✅ Python packages installed!"
```

---

## **STEP 7: Start WhatsApp Bridge (QR Code)**

```bash
cd /root/whatsapp_Telegram_ChatBot/whatsapp-bridge
go run main.go
```

**You'll see a QR code!**
📱 **Scan it with WhatsApp:**
- Open WhatsApp on phone
- Settings → Linked Devices → Link a Device
- Scan the QR code

**After scanning, press `Ctrl+C` to stop**

---

## **STEP 8: Run Services 24/7**

### **Start WhatsApp Bridge (Forever):**
```bash
screen -S whatsapp-bridge
cd /root/whatsapp_Telegram_ChatBot/whatsapp-bridge
go run main.go
```

**When you see "Connected to WhatsApp":**
- Press `Ctrl+A` then `D` (detach from screen)

---

### **Start Python Bot (Forever):**
```bash
screen -S whatsapp-bot
cd /root/whatsapp_Telegram_ChatBot/whatsapp-bot
python3 bot.py
```

**When you see "WhatsApp AI Bot started!":**
- Press `Ctrl+A` then `D` (detach from screen)

---

## **STEP 9: Verify Everything is Running**

```bash
screen -ls
```

**Should show:**
```
2 Sockets in /run/screen/S-root.
    12345.whatsapp-bridge
    12346.whatsapp-bot
```

---

## **STEP 10: Exit Server**

```bash
exit
```

---

## **✅ DONE! Bot is Running 24/7!**

---

## **🔧 Useful Management Commands:**

### **View WhatsApp Bridge Logs:**
```bash
screen -r whatsapp-bridge
# Press Ctrl+A then D to exit
```

### **View Bot Logs:**
```bash
screen -r whatsapp-bot
# Press Ctrl+A then D to exit
```

### **Restart a Service:**
```bash
# Kill old process
screen -X -S whatsapp-bot quit

# Start new one
screen -S whatsapp-bot
cd /root/whatsapp_Telegram_ChatBot/whatsapp-bot
python3 bot.py
# Ctrl+A then D to detach
```

### **Stop Everything:**
```bash
screen -X -S whatsapp-bridge quit
screen -X -S whatsapp-bot quit
```

---

## **📱 Test Your Bot:**

1. Send a WhatsApp message to your number
2. Check Telegram - you should get a notification!
3. Click "Approve" to send AI reply

---

## **🆘 Troubleshooting:**

### **"pip3: command not found"**
```bash
apt install -y python3-pip
```

### **"go: command not found"**
```bash
export PATH=$PATH:/usr/local/go/bin
```

### **WhatsApp Disconnects**
```bash
# Delete old session and scan QR again
cd /root/whatsapp_Telegram_ChatBot/whatsapp-bridge
rm -rf store/*.db
go run main.go
```

### **Bot Crashes (512MB RAM issue)**
- Resize your droplet to 1GB RAM in DigitalOcean dashboard
- Power off → Resize → Power on

---

**That's everything!** Your client can just follow these commands in order. 🎯


