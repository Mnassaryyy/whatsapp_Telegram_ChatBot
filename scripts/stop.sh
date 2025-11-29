#!/bin/bash

echo "Stopping WhatsApp services..."

# Stop screens
screen -S whatsapp-bridge -X quit || pkill -f "go run main.go"
pkill -f "python3 bot.py"

# Stop any whatsapp-bot sessions
for s in $(screen -ls | awk '/whatsapp-bot/{print $1}'); do
    screen -S "$s" -X quit
done
screen -ls#!/bin/bash

echo "Pulling latest updates..."

cd /root/whatsapp_Telegram_ChatBot
git pull origin main

echo "Updating dependencies..."
cd whatsapp-bridge
go get -u go.mau.fi/whatsmeow@latest
go mod tidy

echo "Update complete."

echo "All services stopped."
