"""AI-related helper utilities for the WhatsApp bot.

This module encapsulates:
- Conversation context building from SQLite
- Chat completion invocation with the system prompt
- OpenAI Assistants API integration (thread-based)
- Voice download (via bridge) and transcription (Whisper)
"""

from __future__ import annotations

from typing import List, Dict, Optional, Tuple
import sqlite3
import requests
import time
from config import (
    OPENAI_MODEL, AI_SYSTEM_PROMPT, WHATSAPP_API_URL, WHISPER_LANGUAGE,
    OPENAI_API_MODE, OPENAI_ASSISTANT_ID
)


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
        # Skip empty messages (e.g., voice messages that haven't been transcribed yet)
        if not msg_content or not msg_content.strip():
            continue
        role = "assistant" if is_from_me else "user"
        messages.append({"role": role, "content": msg_content})
    return messages


def _generate_ai_reply_assistants(bot, sender_jid: str, message_text: str, assistant_id: str) -> Optional[str]:
    """Generate an AI reply using OpenAI Assistants API (thread-based).
    
    Based on the assistant_upgrade_position pattern - uses threads for conversation management.
    
    Args:
        bot: The bot instance
        sender_jid: The WhatsApp chat JID (used as thread identifier)
        message_text: The user's message
        assistant_id: The OpenAI Assistant ID to use
    
    Returns:
        The assistant's reply text, or None on error
    """
    try:
        # Step 1: Check if we have an existing thread for this chat, otherwise create new one
        # Using sender_jid as a unique identifier per chat
        thread_id = getattr(bot, '_assistant_threads', {}).get(sender_jid)
        
        if not thread_id:
            # Create a new thread for this chat
            thread = bot.client.beta.threads.create()
            thread_id = thread.id
            
            # Store thread ID for future messages in this chat
            if not hasattr(bot, '_assistant_threads'):
                bot._assistant_threads = {}
            bot._assistant_threads[sender_jid] = thread_id
        
        # Step 2: Add the user's message to the thread
        bot.client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message_text
        )
        
        # Step 3: Run the assistant on that thread
        run = bot.client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id
        )
        
        # Step 4: Wait for the assistant to finish processing
        max_wait = 60  # Maximum 60 seconds
        wait_time = 0
        while wait_time < max_wait:
            run_status = bot.client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            
            if run_status.status == "completed":
                break
            elif run_status.status in ["failed", "cancelled", "expired"]:
                print(f"⚠️  Assistant run failed with status: {run_status.status}", flush=True)
                return None
            
            time.sleep(1)  # Wait 1 second before checking again
            wait_time += 1
        
        if wait_time >= max_wait:
            print(f"⚠️  Assistant run timed out after {max_wait} seconds", flush=True)
            return None
        
        # Step 5: Retrieve the final messages
        messages = bot.client.beta.threads.messages.list(thread_id=thread_id)
        
        # Step 6: Extract the assistant's latest message
        if messages.data and messages.data[0].role == "assistant":
            if messages.data[0].content and len(messages.data[0].content) > 0:
                return messages.data[0].content[0].text.value

        print("⚠️  No assistant response found in thread", flush=True)
        return None
        
        print("⚠️  No assistant response found in thread", flush=True)
        return None
        
    except Exception as e:
        error_msg = str(e)
        error_str_lower = error_msg.lower()
        
        # Check for 404/NotFound errors specifically
        if "404" in error_msg or "not found" in error_str_lower or "no assistant found" in error_str_lower:
            print(f"❌ OpenAI Assistant not found (404): {error_msg}", flush=True)
            print(f"   Please check your OPENAI_ASSISTANT_ID in .env file", flush=True)
            print(f"   Current Assistant ID: {assistant_id}", flush=True)
            print(f"   Tip: Verify the Assistant exists in your OpenAI dashboard at https://platform.openai.com/assistants", flush=True)
            print(f"   You can also switch to Chat Completions API by setting OPENAI_API_MODE=chat in .env", flush=True)
        else:
            print(f"❌ Error running assistant: {error_msg}", flush=True)
            import traceback
            traceback.print_exc()
        return None


def generate_ai_reply(bot, sender_jid: str, message_text: str) -> str:
    """Generate an AI reply using either Chat Completions or Assistants API.
    
    Context is retrieved from the local SQLite database for the given chat (Chat Completions mode).
    Thread-based conversation management is used in Assistants API mode.
    
    The mode is determined by OPENAI_API_MODE config:
    - "chat" (default): Uses Chat Completions API with manual context building
    - "assistants": Uses Assistants API with thread-based conversations
    """
    if OPENAI_API_MODE.lower() == "assistants":
        if not OPENAI_ASSISTANT_ID:
            print("⚠️  OPENAI_ASSISTANT_ID is not set. Falling back to Chat Completions API.", flush=True)
        else:
            reply = _generate_ai_reply_assistants(bot, sender_jid, message_text, OPENAI_ASSISTANT_ID)
            if reply is not None:
                return reply
            else:
                print("⚠️  Assistants API failed. Falling back to Chat Completions API.", flush=True)
        
        # Fallback to Chat Completions if Assistants API fails or is not configured
        print(f"   Using Chat Completions API with model: {OPENAI_MODEL}", flush=True)
        context_messages = _build_context_messages(bot, sender_jid, bot.MAX_CONVERSATION_HISTORY)
        # Add the current message to the context (important for transcribed voice messages that aren't in DB yet)
        context_messages.append({"role": "user", "content": message_text})
        response = bot.client.chat.completions.create(model=OPENAI_MODEL, messages=context_messages)
        return response.choices[0].message.content
    else:
        # Default: Use Chat Completions API
        context_messages = _build_context_messages(bot, sender_jid, bot.MAX_CONVERSATION_HISTORY)
        # Add the current message to the context (important for transcribed voice messages that aren't in DB yet)
        context_messages.append({"role": "user", "content": message_text})
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


