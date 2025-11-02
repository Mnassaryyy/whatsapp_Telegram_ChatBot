"""Media-related helpers: download via bridge, Telegram send, and formatting.

All functions are defensive (gracefully handle missing files/paths) and avoid
proxy interference by disabling proxies for local bridge traffic.
"""

from __future__ import annotations

import os
import requests
import sqlite3
from typing import Tuple

from config import WHATSAPP_API_URL


def download_media(bot, message_id: str, chat_jid: str) -> Tuple[bool, str, str, str]:
    """Ask the bridge to download media.

    Returns (ok, media_type_message, filename, abs_path).
    """
    try:
        url = f"{WHATSAPP_API_URL}/download"
        resp = requests.post(
            url,
            json={"message_id": message_id, "chat_jid": chat_jid},
            timeout=12,
            proxies={"http": None, "https": None},
        )
        data = resp.json()
        if not data.get("success"):
            return False, "", "", ""
        return True, data.get("Message", ""), data.get("Filename", ""), data.get("Path", "")
    except Exception:
        return False, "", "", ""


async def send_telegram_media(bot, media_type: str, media_path: str, caption: str) -> None:
    """Send the specified media to Telegram with an appropriate method.

    image -> send_photo, video -> send_video, otherwise send_document.
    """
    try:
        if not os.path.isabs(media_path):
            media_path = os.path.abspath(media_path)
        if not os.path.exists(media_path):
            return
        if media_type == "image":
            with open(media_path, "rb") as f:
                await bot.telegram_app.bot.send_photo(chat_id=bot.YOUR_TELEGRAM_CHAT_ID, photo=f, caption=caption)
        elif media_type == "video":
            with open(media_path, "rb") as f:
                await bot.telegram_app.bot.send_video(chat_id=bot.YOUR_TELEGRAM_CHAT_ID, video=f, caption=caption)
        else:
            with open(media_path, "rb") as f:
                await bot.telegram_app.bot.send_document(chat_id=bot.YOUR_TELEGRAM_CHAT_ID, document=f, caption=caption)
    except Exception:
        return


def find_recent_media_in_store(chat_jid: str) -> str:
    """Find the most recently modified file under store/<chat_jid> as a fallback."""
    try:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "whatsapp-bridge", "store", chat_jid))
        if not os.path.isdir(base):
            return ""
        latest_path = ""; latest_mtime = 0
        for root, _, files in os.walk(base):
            for name in files:
                p = os.path.join(root, name)
                try:
                    m = os.path.getmtime(p)
                    if m > latest_mtime:
                        latest_mtime = m; latest_path = p
                except Exception:
                    pass
        return latest_path
    except Exception:
        return ""


def get_media_size_bytes(db_path: str, message_id: str, chat_jid: str) -> int:
    """Read media size (file_length) from messages table if present."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor(); cur.execute("SELECT file_length FROM messages WHERE id=? AND chat_jid=?", (message_id, chat_jid))
        r = cur.fetchone(); conn.close()
        if r and r[0]:
            return int(r[0])
    except Exception:
        pass
    return 0


def format_size(num_bytes: int) -> str:
    """Human-readable size string (e.g., 1.2 MB)."""
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    i = 0
    while size >= 1024 and i < len(units)-1:
        size /= 1024.0; i += 1
    return f"{size:.1f} {units[i]}" if num_bytes > 0 else "unknown"


