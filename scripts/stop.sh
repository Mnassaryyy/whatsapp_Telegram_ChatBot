#!/bin/bash

echo "Stopping WhatsApp services..."

# Stop screens
screen -S whatsapp-bridge -X quit || pkill -f "go run main.go"
pkill -f "python3 bot.py"

# Stop any whatsapp-bot sessions
for s in $(screen -ls | awk '/whatsapp-bot/{print $1}'); do
    screen -S "$s" -X quit
done

echo "All services stopped."
screen -ls
