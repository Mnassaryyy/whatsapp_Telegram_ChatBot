#!/usr/bin/env python3
"""Quick diagnostic script to check bot status"""

import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

# Load .env
env_path = Path(__file__).parent / "whatsapp-bot" / ".env"
load_dotenv(dotenv_path=env_path)

DATABASE_PATH = os.getenv("DATABASE_PATH", "../whatsapp-bridge/store/messages.db")

print("=" * 60)
print("Bot Status Check")
print("=" * 60)

# Check database
db_path = os.path.abspath(DATABASE_PATH) if not os.path.isabs(DATABASE_PATH) else DATABASE_PATH
print(f"\n📂 Database Path: {db_path}")
print(f"   Exists: {os.path.exists(db_path)}")

if os.path.exists(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check messages
        cursor.execute("SELECT COUNT(*) FROM messages WHERE is_from_me = 0")
        incoming_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM messages")
        total_count = cursor.fetchone()[0]
        
        # Get latest message
        cursor.execute("""
            SELECT timestamp, sender, content 
            FROM messages 
            WHERE is_from_me = 0 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        latest = cursor.fetchone()
        
        print(f"   Total messages: {total_count}")
        print(f"   Incoming messages: {incoming_count}")
        if latest:
            print(f"   Latest message: {latest[0]} from {latest[1]}")
            print(f"   Content: {latest[2][:50] if latest[2] else 'N/A'}...")
        
        conn.close()
    except Exception as e:
        print(f"   ❌ Error reading database: {e}")

# Check bridge API
import requests
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "http://localhost:8080/api")
print(f"\n🌉 Bridge API: {WHATSAPP_API_URL}")
try:
    resp = requests.get(f"{WHATSAPP_API_URL}/send", timeout=2)
    print(f"   Status: ✅ Responding (HTTP {resp.status_code})")
except Exception as e:
    print(f"   Status: ❌ Not responding - {e}")

# Check Telegram config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YOUR_TELEGRAM_CHAT_ID = os.getenv("YOUR_TELEGRAM_CHAT_ID")
print(f"\n📱 Telegram Config:")
print(f"   Bot Token: {'✅ Set' if TELEGRAM_BOT_TOKEN else '❌ Missing'}")
print(f"   Chat ID: {'✅ Set' if YOUR_TELEGRAM_CHAT_ID else '❌ Missing'}")

# Check OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
print(f"\n🤖 OpenAI Config:")
print(f"   API Key: {'✅ Set' if OPENAI_API_KEY else '❌ Missing'}")

print("\n" + "=" * 60)

