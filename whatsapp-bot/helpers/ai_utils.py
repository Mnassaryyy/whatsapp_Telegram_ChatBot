"""AI-related helper utilities for the WhatsApp bot.

This module encapsulates:
- Conversation context building from SQLite
- Chat completion invocation with the system prompt
- Voice download (via bridge) and transcription (Whisper)
"""

from __future__ import annotations

from typing import List, Dict, Optional, Tuple
import sqlite3
import requests
from config import OPENAI_MODEL, AI_SYSTEM_PROMPT, WHATSAPP_API_URL, WHISPER_LANGUAGE


def _build_context_messages(bot, sender_jid: str, max_messages: int) -> List[Dict[str, str]]:
    """Build an ordered chat history with a system prompt.

    Returns a list of messages suitable for OpenAI chat completions.
    Older messages appear earlier; newest last.
    """
    conn = sqlite3.connect(bot.DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT content, is_from_me, timestamp
        FROM messages
        WHERE chat_jid = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (sender_jid, max_messages),
    )
    history = cursor.fetchall()
    conn.close()

    messages: List[Dict[str, str]] = [{"role": "system", "content": AI_SYSTEM_PROMPT}]
    for msg_content, is_from_me, _ in reversed(history):
        role = "assistant" if is_from_me else "user"
        messages.append({"role": role, "content": msg_content})
    return messages


def generate_ai_reply(bot, sender_jid: str, message_text: str) -> str:
    """Generate an AI reply using OpenAI chat completions.

    Context is retrieved from the local SQLite database for the given chat.
    """
    context_messages = _build_context_messages(bot, sender_jid, bot.MAX_CONVERSATION_HISTORY)
    response = bot.client.chat.completions.create(model=OPENAI_MODEL, messages=context_messages)
    return response.choices[0].message.content


def transcribe_voice_message(bot, message_id: str, chat_jid: str) -> Optional[str]:
    """Download and transcribe a voice message via the bridge and Whisper.

    Returns transcription text if successful, otherwise None.
    """
    try:
        resp = requests.post(
            f"{WHATSAPP_API_URL}/download",
            json={"message_id": message_id, "chat_jid": chat_jid},
            timeout=20,
            proxies={"http": None, "https": None},
        )
        data = resp.json()
        if not data.get("success"):
            return None
        audio_path = data.get("Path") or data.get("path")
        if not audio_path:
            return None

        with open(audio_path, "rb") as audio_file:
            lang = WHISPER_LANGUAGE if WHISPER_LANGUAGE and WHISPER_LANGUAGE.lower() != "none" else None
            if lang:
                transcription = bot.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=lang,
                    response_format="text",
                )
            else:
                transcription = bot.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text",
                )
        return transcription
    except Exception:
        return None


