@echo off
echo Starting WhatsApp AI Bot...
echo.
echo NOTE: For Telegram QR code support, use START_BOT.ps1 instead
echo (Right-click START_BOT.ps1 -^> Run with PowerShell)
echo.
echo Alternatively, set environment variables manually:
echo   set TELEGRAM_BOT_TOKEN=your_token
echo   set YOUR_TELEGRAM_CHAT_ID=your_chat_id
echo.

REM Start WhatsApp Bridge in new window
echo [1/2] Starting WhatsApp Bridge...
echo WARNING: Telegram env vars not set - QR codes won't be sent to Telegram!
start "WhatsApp Bridge" cmd /k "cd whatsapp-bridge && go run main.go"

REM Wait for bridge to start
timeout /t 5 /nobreak

REM Start Python Bot
echo [2/2] Starting AI Bot...
cd whatsapp-bot
python bot.py

pause



