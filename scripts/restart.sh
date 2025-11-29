#!/bin/bash

echo "Restarting services..."

BRIDGE_DIR=/root/whatsapp_Telegram_ChatBot/whatsapp-bridge
BOT_DIR=/root/whatsapp_Telegram_ChatBot/whatsapp-bot

screen -S whatsapp-bridge -dm bash -lc "cd $BRIDGE_DIR && go run main.go"
sleep 3
screen -S whatsapp-bot -dm bash -lc "cd $BOT_DIR && python3 bot.py"

echo "Services restarted."

screen -ls
