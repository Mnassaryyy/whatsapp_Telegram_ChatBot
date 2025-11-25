# PowerShell script to start WhatsApp Bridge with Telegram env vars
# This reads .env from whatsapp-bot folder and passes Telegram credentials to bridge

Write-Host "Starting WhatsApp AI Bot..." -ForegroundColor Green
Write-Host ""

# Get the script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$botDir = Join-Path $scriptDir "whatsapp-bot"
$bridgeDir = Join-Path $scriptDir "whatsapp-bridge"
$envFile = Join-Path $botDir ".env"

# Read .env file
if (-not (Test-Path $envFile)) {
    Write-Host "ERROR: .env file not found at $envFile" -ForegroundColor Red
    Write-Host "Please create .env file in whatsapp-bot folder" -ForegroundColor Yellow
    exit 1
}

Write-Host "[1/2] Reading Telegram credentials from .env..." -ForegroundColor Cyan

# Read .env file and extract Telegram credentials
$telegramToken = $null
$telegramChatId = $null

Get-Content $envFile | ForEach-Object {
    if ($_ -match '^TELEGRAM_BOT_TOKEN=(.+)$') {
        $telegramToken = $matches[1].Trim().Trim('"').Trim("'")
    }
    if ($_ -match '^YOUR_TELEGRAM_CHAT_ID=(.+)$') {
        $telegramChatId = $matches[1].Trim().Trim('"').Trim("'")
    }
}

if ([string]::IsNullOrEmpty($telegramToken) -or [string]::IsNullOrEmpty($telegramChatId)) {
    Write-Host "WARNING: TELEGRAM_BOT_TOKEN or YOUR_TELEGRAM_CHAT_ID not found in .env" -ForegroundColor Yellow
    Write-Host "QR codes will not be sent to Telegram" -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-Host "Telegram credentials found!" -ForegroundColor Green
    Write-Host ""
}

# Start WhatsApp Bridge with environment variables
Write-Host "[2/2] Starting WhatsApp Bridge..." -ForegroundColor Cyan
Write-Host ""

if ($telegramToken -and $telegramChatId) {
    # Set environment variables and start bridge
    $env:TELEGRAM_BOT_TOKEN = $telegramToken
    $env:YOUR_TELEGRAM_CHAT_ID = $telegramChatId
    
    Start-Process cmd -ArgumentList "/k", "cd /d `"$bridgeDir`" && go run main.go" -WindowStyle Normal
} else {
    # Start bridge without Telegram env vars
    Start-Process cmd -ArgumentList "/k", "cd /d `"$bridgeDir`" && go run main.go" -WindowStyle Normal
}

Write-Host "Bridge started in new window" -ForegroundColor Green
Write-Host "Waiting 5 seconds..." -ForegroundColor Cyan
Start-Sleep -Seconds 5

# Start Python Bot
Write-Host "[3/3] Starting AI Bot..." -ForegroundColor Cyan
Set-Location $botDir
python bot.py

