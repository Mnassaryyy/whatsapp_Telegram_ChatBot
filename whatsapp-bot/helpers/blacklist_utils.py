"""Blacklist management utilities for WhatsApp bot.

Allows blocking users so their messages don't appear on Telegram.
"""

from __future__ import annotations

from typing import List, Optional
import sqlite3
from datetime import datetime


def init_blacklist_table(db_path: str) -> None:
    """Initialize blacklist table in database if it doesn't exist."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS blacklist (
                chat_jid TEXT PRIMARY KEY,
                blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reason TEXT,
                notes TEXT
            );
            """
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Failed to create blacklist table: {e}", flush=True)


def is_blacklisted(db_path: str, chat_jid: str) -> bool:
    """Check if a chat JID is blacklisted."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT chat_jid FROM blacklist WHERE chat_jid = ?",
            (chat_jid,)
        )
        result = cur.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        print(f"⚠️  Error checking blacklist: {e}", flush=True)
        return False


def add_to_blacklist(
    db_path: str,
    chat_jid: str,
    reason: Optional[str] = None,
    notes: Optional[str] = None
) -> bool:
    """Add a chat JID to the blacklist."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO blacklist (chat_jid, blocked_at, reason, notes)
            VALUES (?, CURRENT_TIMESTAMP, ?, ?)
            """,
            (chat_jid, reason, notes)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error adding to blacklist: {e}", flush=True)
        return False


def remove_from_blacklist(db_path: str, chat_jid: str) -> bool:
    """Remove a chat JID from the blacklist."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM blacklist WHERE chat_jid = ?",
            (chat_jid,)
        )
        conn.commit()
        removed = cur.rowcount > 0
        conn.close()
        return removed
    except Exception as e:
        print(f"❌ Error removing from blacklist: {e}", flush=True)
        return False


def get_blacklist_info(db_path: str, chat_jid: str) -> Optional[dict]:
    """Get blacklist information for a chat JID."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT chat_jid, blocked_at, reason, notes FROM blacklist WHERE chat_jid = ?",
            (chat_jid,)
        )
        result = cur.fetchone()
        conn.close()
        
        if result:
            return {
                "chat_jid": result[0],
                "blocked_at": result[1],
                "reason": result[2],
                "notes": result[3],
            }
        return None
    except Exception as e:
        print(f"⚠️  Error getting blacklist info: {e}", flush=True)
        return None


def list_blacklisted(db_path: str, limit: int = 50) -> List[dict]:
    """Get list of all blacklisted users."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT chat_jid, blocked_at, reason, notes FROM blacklist ORDER BY blocked_at DESC LIMIT ?",
            (limit,)
        )
        results = cur.fetchall()
        conn.close()
        
        blacklisted = []
        for row in results:
            blacklisted.append({
                "chat_jid": row[0],
                "blocked_at": row[1],
                "reason": row[2],
                "notes": row[3],
            })
        return blacklisted
    except Exception as e:
        print(f"⚠️  Error listing blacklist: {e}", flush=True)
        return []

