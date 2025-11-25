"""Batching helpers for fragmented text concatenation.

Maintains per-chat buffers and flushes them when idle long enough.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

from openai import RateLimitError

from .ai_utils import generate_ai_reply


def buffer_add_text(bot, chat_jid: str, msg_id: str, sender_name: str, text: str, timestamp) -> None:
    """Add incoming text to the per-chat buffer and update last timestamp."""
    try:
        if not text:
            return
        if isinstance(timestamp, str):
            ts = datetime.fromisoformat(timestamp.replace(' ', 'T'))
        else:
            ts = timestamp
        if getattr(ts, 'tzinfo', None) is not None:
            ts = ts.replace(tzinfo=None)
        buf = bot.incoming_buffers.get(chat_jid)
        if not buf:
            buf = {"texts": [], "last_msg_id": msg_id, "sender_name": sender_name or chat_jid, "last_timestamp": ts}
            bot.incoming_buffers[chat_jid] = buf
        buf["texts"].append(text)
        buf["last_msg_id"] = msg_id
        buf["sender_name"] = sender_name or chat_jid
        buf["last_timestamp"] = ts
    except Exception:
        pass


def flush_ready_buffers(bot, joiner: str = " \n") -> bool:
    """Flush buffers idle for >= bot.batch_window_sec. Returns True if anything enqueued.

    joiner controls how individual fragments are concatenated (default newline).
    """
    now = datetime.now()
    enqueued_any = False
    try:
        for chat_jid in list(bot.incoming_buffers.keys()):
            buf = bot.incoming_buffers.get(chat_jid)
            if not buf or not buf.get("texts"):
                continue
            last_ts = buf.get("last_timestamp")
            if not last_ts:
                continue
            if getattr(last_ts, 'tzinfo', None) is not None:
                last_ts = last_ts.replace(tzinfo=None)
            idle = (now - last_ts).total_seconds()
            idle_min = int(idle // 60)
            idle_sec = int(idle % 60)
            if idle >= bot.batch_window_sec:
                combined = joiner.join(buf["texts"]).strip()
                last_msg_id = buf.get("last_msg_id")
                sender_name = buf.get("sender_name")
                print(f"🔄 Flushing buffer for {sender_name} (idle {idle_min}m {idle_sec}s, {len(buf['texts'])} message(s))...", flush=True)
                try:
                    ai_reply = generate_ai_reply(bot, chat_jid, combined)
                    print(f"🤖 AI Reply generated for {sender_name}", flush=True)
                    ts = last_ts
                    row_number = bot.log_to_sheets(ts, chat_jid, sender_name, combined, ai_reply)
                    bot.enqueue_item(last_msg_id, chat_jid, sender_name, combined, "", "", ai_reply, row_number)
                    print(f"✅ Enqueued message from {sender_name} for Telegram", flush=True)
                    enqueued_any = True
                    bot.incoming_buffers.pop(chat_jid, None)
                except RateLimitError as e:
                    error_msg = str(e)
                    if "insufficient_quota" in error_msg.lower() or "quota" in error_msg.lower():
                        print(f"⚠️  OpenAI quota exceeded! Keeping buffer for retry. Please check your OpenAI billing.", flush=True)
                        print(f"   Buffer will be retried when quota is restored. Message: {combined[:50]}...", flush=True)
                    else:
                        print(f"⚠️  OpenAI rate limit hit! Keeping buffer for retry. Will retry later.", flush=True)
                    # Keep buffer for retry - don't pop it
                except Exception as e:
                    error_msg = str(e)
                    print(f"❌ Error flushing buffer: {error_msg}", flush=True)
                    import traceback
                    traceback.print_exc()
                    # For other errors, still clear buffer to avoid infinite retry
                    bot.incoming_buffers.pop(chat_jid, None)
            else:
                # Log buffer status
                remaining = bot.batch_window_sec - idle
                remaining_min = int(remaining // 60)
                remaining_sec = int(remaining % 60)
                if len(buf.get("texts", [])) > 0:
                    print(f"⏳ Buffer for {buf.get('sender_name', chat_jid)}: {len(buf['texts'])} message(s), waiting {remaining_min}m {remaining_sec}s more...", flush=True)
    except Exception as e:
        print(f"❌ Error in flush_ready_buffers: {e}", flush=True)
        import traceback
        traceback.print_exc()
    return enqueued_any


