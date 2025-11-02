"""Queue helpers for enqueueing, activation, and status updates.

These functions encapsulate all SQLite interactions for the approval queue.
"""

from __future__ import annotations

import sqlite3
from typing import Optional, Tuple, Any


def is_greeting(text: str) -> bool:
    """Heuristic to bump priority for short greeting-like messages."""
    if not text:
        return False
    t = text.strip().lower()
    keywords = ("hi", "hello", "hey", "assalam", "good morning", "good evening", "good night", "salam")
    return any(k in t for k in keywords) and len(t) <= 30


def enqueue_item(
    db_path: str,
    message_id: str,
    chat_jid: str,
    sender_name: str,
    content: str,
    media_type: str,
    media_path: str,
    ai_reply: str,
    row_number: int,
    priority: int,
) -> None:
    """Insert an item into the queue with 'pending' status."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO queue_items (message_id, chat_jid, sender_name, content, media_type, media_path, ai_reply, row_number, status, priority, last_transition_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
            """,
            (message_id, chat_jid, sender_name or chat_jid, content or "", media_type or "", media_path or "", ai_reply or "", row_number or 0, priority),
        )
        conn.commit(); conn.close()
    except Exception:
        pass


def get_active_item(db_path: str):
    """Return the active item or None."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor(); cur.execute("SELECT id, message_id, chat_jid, sender_name, content, media_type, media_path, ai_reply, row_number FROM queue_items WHERE status='active' ORDER BY id LIMIT 1")
        row = cur.fetchone(); conn.close(); return row
    except Exception:
        return None


def activate_next_pending(db_path: str):
    """Transition the next pending item to active and return it."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor(); cur.execute("SELECT id FROM queue_items WHERE status='pending' ORDER BY priority ASC, created_at ASC LIMIT 1")
        row = cur.fetchone()
        if not row:
            conn.close(); return None
        qid = row[0]
        cur.execute("UPDATE queue_items SET status='active', last_transition_at=CURRENT_TIMESTAMP WHERE id=?", (qid,))
        conn.commit(); cur.execute("SELECT id, message_id, chat_jid, sender_name, content, media_type, media_path, ai_reply, row_number FROM queue_items WHERE id=?", (qid,))
        item = cur.fetchone(); conn.close(); return item
    except Exception:
        return None


def mark_item_status(db_path: str, qid: int, status: str) -> None:
    """Update status and timestamp for a queued item."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor(); cur.execute("UPDATE queue_items SET status=?, last_transition_at=CURRENT_TIMESTAMP WHERE id=?", (status, qid))
        conn.commit(); conn.close()
    except Exception:
        pass


def pending_count(db_path: str) -> int:
    """Count pending items."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor(); cur.execute("SELECT COUNT(1) FROM queue_items WHERE status='pending'")
        n = cur.fetchone()[0]; conn.close(); return int(n)
    except Exception:
        return 0


