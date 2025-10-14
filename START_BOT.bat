@echo off
echo Starting WhatsApp AI Bot...
echo.

REM Start WhatsApp Bridge in new window
echo [1/2] Starting WhatsApp Bridge...
start "WhatsApp Bridge" cmd /k "cd whatsapp-bridge && go run main.go"

REM Wait for bridge to start
timeout /t 5 /nobreak

REM Start Python Bot
echo [2/2] Starting AI Bot...
cd whatsapp-bot
python bot.py

pause



