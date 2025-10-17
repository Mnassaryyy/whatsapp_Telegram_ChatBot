#!/bin/bash
# Quick deployment script for DigitalOcean

echo "🚀 WhatsApp AI Bot - DigitalOcean Deployment"
echo "=============================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run as root: sudo bash deploy.sh"
    exit 1
fi

echo "📦 Step 1: Installing system packages..."
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git ffmpeg screen

echo ""
echo "🔧 Step 2: Installing Go..."
if ! command -v go &> /dev/null; then
    wget -q https://go.dev/dl/go1.21.6.linux-amd64.tar.gz
    tar -C /usr/local -xzf go1.21.6.linux-amd64.tar.gz
    echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc
    export PATH=$PATH:/usr/local/go/bin
    rm go1.21.6.linux-amd64.tar.gz
    echo "✅ Go installed"
else
    echo "✅ Go already installed"
fi

echo ""
echo "🐍 Step 3: Installing Python dependencies..."
cd whatsapp-bot
pip3 install -r requirements.txt

echo ""
echo "📝 Step 4: Checking configuration..."
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found!"
    echo "Please create .env file with your credentials"
    echo "See env.example for reference"
    exit 1
fi

if [ ! -f "credentials.json" ]; then
    echo "⚠️  credentials.json not found!"
    echo "Please upload your Google Service Account credentials"
    exit 1
fi

echo "✅ Configuration files found"

echo ""
echo "🎯 Step 5: Setting up systemd services..."

# WhatsApp Bridge Service
cat > /etc/systemd/system/whatsapp-bridge.service << 'EOF'
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
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Python Bot Service
cat > /etc/systemd/system/whatsapp-bot.service << 'EOF'
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
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable whatsapp-bridge
systemctl enable whatsapp-bot

echo "✅ Services created and enabled"

echo ""
echo "📱 Step 6: Starting WhatsApp Bridge (QR Code will appear)..."
echo "⚠️  IMPORTANT: You need to scan the QR code with your phone!"
echo ""
cd ../whatsapp-bridge
go run main.go &
BRIDGE_PID=$!

echo ""
echo "👆 Scan the QR code above with WhatsApp on your phone"
echo ""
read -p "Press Enter after scanning the QR code..."

# Kill the temporary process
kill $BRIDGE_PID 2>/dev/null

echo ""
echo "🚀 Step 7: Starting services..."
systemctl start whatsapp-bridge
sleep 3
systemctl start whatsapp-bot

echo ""
echo "✅ Deployment Complete!"
echo ""
echo "📊 Service Status:"
systemctl status whatsapp-bridge --no-pager | head -3
systemctl status whatsapp-bot --no-pager | head -3

echo ""
echo "📝 Useful Commands:"
echo "  View logs:       journalctl -u whatsapp-bot -f"
echo "  Restart bot:     systemctl restart whatsapp-bot"
echo "  Check status:    systemctl status whatsapp-bot"
echo ""
echo "🎉 Your bot is now running 24/7!"

