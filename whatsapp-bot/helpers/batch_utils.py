"""Batching helpers for fragmented text concatenation.

Maintains per-chat buffers and flushes them when idle long enough.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

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
            if idle >= bot.batch_window_sec:
                combined = joiner.join(buf["texts"]).strip()
                last_msg_id = buf.get("last_msg_id")
                sender_name = buf.get("sender_name")
                try:
                    ai_reply = generate_ai_reply(bot, chat_jid, combined)
                    ts = last_ts
                    row_number = bot.log_to_sheets(ts, chat_jid, sender_name, combined, ai_reply)
                    bot.enqueue_item(last_msg_id, chat_jid, sender_name, combined, "", "", ai_reply, row_number)
                    enqueued_any = True
                except Exception:
                    pass
                bot.incoming_buffers.pop(chat_jid, None)
    except Exception:
        pass
    return enqueued_any


