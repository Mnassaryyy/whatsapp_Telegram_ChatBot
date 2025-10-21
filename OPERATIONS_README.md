## WhatsApp AI Bot — Operations Cheat Sheet

Keep this handy for day‑to‑day ops on VPS and local.

### SSH Connection
```bash
# Default
ssh root@YOUR_VPS_IP

# Custom port
ssh -p 2222 root@YOUR_VPS_IP

# With key (Windows example)
ssh -i C:\Users\Admin\.ssh\id_rsa_digitalocean root@YOUR_VPS_IP
```

### Service Paths (VPS)
```bash
BRIDGE_DIR=/root/whatsapp_Telegram_ChatBot/whatsapp-bridge
BOT_DIR=/root/whatsapp_Telegram_ChatBot/whatsapp-bot
```

### Start Services (screen)
```bash
# Start WhatsApp bridge
screen -S whatsapp-bridge -dm bash -lc "cd $BRIDGE_DIR && go run main.go"

# Start Python bot
screen -S whatsapp-bot -dm bash -lc "cd $BOT_DIR && python3 bot.py"
```

### Check Status
```bash
# See screen sessions
screen -ls | grep whatsapp-

# Bot process
pgrep -fl "python3 bot.py" || true

# Bridge listening on 8080
ss -ltnp | grep :8080 || sudo lsof -iTCP:8080 -sTCP:LISTEN || true

# Bridge health (405 == up, method not allowed)
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/api/send
```

### View Logs (attach)
```bash
screen -r whatsapp-bridge
screen -r whatsapp-bot

# Detach without stopping: Ctrl+A then D
```

### Stop / Restart
```bash
# Stop bridge (screen)
screen -S whatsapp-bridge -X quit || true

# Stop bot
pkill -f "python3 bot.py" || true
for s in $(screen -ls | awk '/whatsapp-bot/{print $1}'); do screen -S "$s" -X quit; done

# Restart
screen -S whatsapp-bridge -dm bash -lc "cd $BRIDGE_DIR && go run main.go"
screen -S whatsapp-bot -dm bash -lc "cd $BOT_DIR && python3 bot.py"
```

### WhatsApp Logout / Reset (VPS)
```bash
screen -S whatsapp-bridge -X quit || true
cd $BRIDGE_DIR
rm -f store/whatsapp.db            # logout session only
# rm -f store/*.db                 # full reset incl. message history (optional)
screen -S whatsapp-bridge -dm bash -lc "cd $BRIDGE_DIR && go run main.go"
screen -r whatsapp-bridge          # scan QR in WhatsApp → Linked Devices
```

### Direct Send Test (Bridge API)
```bash
# Should return HTTP 405 (endpoint exists)
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/api/send

# Send a test message to a JID (example)
curl -s -X POST http://127.0.0.1:8080/api/send -H "Content-Type: application/json" \
  -d '{"recipient":"201114108083@s.whatsapp.net","message":"Bridge test"}'

# Get last incoming chat_jid without sqlite3 (Python)
cd $BOT_DIR
python3 - <<'PY'
import sqlite3; c=sqlite3.connect("../whatsapp-bridge/store/messages.db").cursor()
c.execute("select chat_jid from messages where is_from_me=0 order by timestamp desc limit 1;")
r=c.fetchone(); print(r[0] if r else "")
PY
```

### Bot Environment (.env) Quick Edits (VPS)
```bash
cd $BOT_DIR
# Ensure bridge URL uses IPv4 localhost
sed -i 's|^WHATSAPP_API_URL=.*|WHATSAPP_API_URL=http://127.0.0.1:8080/api|' .env

# (Optional) avoid proxies for localhost
grep -q '^NO_PROXY=' .env || echo 'NO_PROXY=127.0.0.1,localhost' >> .env
grep -q '^no_proxy=' .env || echo 'no_proxy=127.0.0.1,localhost' >> .env

# Restart bot to load changes
pkill -f "python3 bot.py" || true
screen -S whatsapp-bot -dm bash -lc "cd $BOT_DIR && python3 bot.py"
```

### Telegram Bot Token Check
```bash
cd $BOT_DIR
python3 - <<'PY'
from dotenv import load_dotenv; load_dotenv(); import os, requests
t=os.getenv("TELEGRAM_BOT_TOKEN"); print("Token present:", bool(t))
print(requests.get(f"https://api.telegram.org/bot{t}/getMe").text)
PY
```

### Approve & Send — Troubleshooting
```bash
# 1) Watch bridge while tapping Approve (expect a POST to /api/send)
screen -r whatsapp-bridge

# 2) Watch bot for handler errors on click
screen -r whatsapp-bot

# 3) Network proof of POST to 8080 when tapping Approve
sudo tcpdump -i lo -nn port 8080

# 4) Ensure only one bot instance is polling
screen -ls | grep whatsapp-bot || true
pgrep -fl "python3 bot.py" || true

# 5) Disable Markdown in Telegram edits (quick safety)
sed -i "s/, parse_mode='Markdown'//" $BOT_DIR/bot.py
pkill -f "python3 bot.py" || true
screen -S whatsapp-bot -dm bash -lc "cd $BOT_DIR && python3 bot.py"
```

### Local (Windows) Run
```powershell
# Bridge (scan QR)
cd E:\Mnassary\whatsapp-mcp\whatsapp-bridge
go run main.go

# Bot (venv)
cd E:\Mnassary\whatsapp-mcp\whatsapp-bot
python -m venv .venv
.\.venv\Scripts\Activate
pip install -r requirements.txt
copy env.example .env  # if needed, then fill keys
python bot.py
```

### Common Hotkeys
- Detach screen session: Ctrl+A then D
- Reattach: `screen -r SESSION_NAME`
- Stop screen session: `screen -S SESSION_NAME -X quit`

### Quick Reference
- Only one Telegram bot instance may poll at a time.
- Use `http://127.0.0.1:8080/api` for the bot → bridge URL on VPS.
- Use fresh Telegram approval cards after restarts.

