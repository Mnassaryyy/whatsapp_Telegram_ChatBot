"""Telegram UI helpers: safe edits and common keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


async def safe_edit(query, text: str, parse_mode=None):
    """Edit text or caption depending on message type."""
    try:
        msg = query.message
        if msg and (getattr(msg, 'photo', None) or getattr(msg, 'video', None) or getattr(msg, 'document', None)):
            await query.edit_message_caption(caption=text, parse_mode=parse_mode)
        else:
            await query.edit_message_text(text, parse_mode=parse_mode)
    except Exception:
        return


def build_notification_keyboard(message_id: str) -> InlineKeyboardMarkup:
    """Keyboard used in simple notification flows."""
    keyboard = [[
        InlineKeyboardButton("✅ Approve & Send", callback_data=f"approve_{message_id}"),
        InlineKeyboardButton("🎤 Record Own", callback_data=f"record_{message_id}"),
    ]]
    return InlineKeyboardMarkup(keyboard)


def build_full_approval_keyboard(message_id: str) -> InlineKeyboardMarkup:
    """Keyboard used on the main approval card (with more actions)."""
    keyboard = [[
        InlineKeyboardButton("✅ Approve & Send", callback_data=f"approve_{message_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{message_id}"),
    ], [
        InlineKeyboardButton("🎤 Record Own", callback_data=f"record_{message_id}"),
        InlineKeyboardButton("✍️ Custom Message", callback_data=f"custom_{message_id}"),
        InlineKeyboardButton("🕓 Reply Later", callback_data=f"later_{message_id}"),
    ]]
    return InlineKeyboardMarkup(keyboard)


