"""WhatsApp bridge API helpers (send endpoints)."""

from __future__ import annotations

import os
import requests
from typing import Optional

from config import WHATSAPP_API_URL


def send_text(recipient: str, message: str, timeout: int = 10) -> bool:
    """Send a text message via the bridge /send endpoint."""
    try:
        resp = requests.post(
            f"{WHATSAPP_API_URL}/send",
            json={"recipient": recipient, "message": message},
            timeout=timeout,
        )
        return bool(resp.json().get("success", False))
    except Exception:
        return False


def send_voice(recipient: str, voice_path: str, timeout: int = 10) -> bool:
    """Send a voice (audio) file via the bridge /send endpoint."""
    try:
        resp = requests.post(
            f"{WHATSAPP_API_URL}/send",
            json={"recipient": recipient, "message": "", "media_path": voice_path},
            timeout=timeout,
        )
        return bool(resp.json().get("success", False))
    except Exception:
        return False


def send_media(recipient: str, media_path: str, timeout: int = 30) -> bool:
    """Send any media file path via the bridge /send endpoint (document/image/video)."""
    try:
        resp = requests.post(
            f"{WHATSAPP_API_URL}/send",
            json={"recipient": recipient, "message": "", "media_path": media_path},
            timeout=timeout,
        )
        return bool(resp.json().get("success", False))
    except Exception:
        return False


