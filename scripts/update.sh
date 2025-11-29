#!/bin/bash

echo "Pulling latest updates..."

cd /root/whatsapp_Telegram_ChatBot
git pull origin main

echo "Updating dependencies..."
cd whatsapp-bridge
go get -u go.mau.fi/whatsmeow@latest
go mod tidy

cd ../whatsapp-bot
pip3 install -r requirements.txt

echo "Update complete."

