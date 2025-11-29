"""Subscription management utilities for WhatsApp bot.

Supports 3-tier subscription model:
- FREE: Basic features, limited messages
- BASIC: Standard features, moderate limits
- PREMIUM: Full features, unlimited or high limits
"""

from __future__ import annotations

from typing import Optional, Dict, Tuple
import sqlite3
from datetime import datetime, timedelta
from enum import Enum


class SubscriptionTier(Enum):
    """Subscription tier levels"""
    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"


# Tier configuration: limits per day
TIER_LIMITS = {
    SubscriptionTier.FREE: {
        "daily_messages": 10,  # Max AI replies per day
        "voice_transcription": False,  # No voice transcription
        "priority_processing": False,  # Standard processing
        "batch_window_override": None,  # Use default batch window
    },
    SubscriptionTier.BASIC: {
        "daily_messages": 50,
        "voice_transcription": True,
        "priority_processing": False,
        "batch_window_override": 600,  # 10 minutes instead of 20
    },
    SubscriptionTier.PREMIUM: {
        "daily_messages": -1,  # -1 means unlimited
        "voice_transcription": True,
        "priority_processing": True,
        "batch_window_override": 0,  # Instant processing (0 seconds)
    }
}


def init_subscriptions_table(db_path: str) -> None:
    """Initialize subscriptions table in database if it doesn't exist."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                chat_jid TEXT PRIMARY KEY,
                tier TEXT NOT NULL DEFAULT 'free',
                daily_message_count INTEGER DEFAULT 0,
                last_reset_date DATE DEFAULT CURRENT_DATE,
                subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                notes TEXT
            );
            """
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Failed to create subscriptions table: {e}", flush=True)


def get_subscription_tier(db_path: str, chat_jid: str) -> SubscriptionTier:
    """Get subscription tier for a chat JID. Returns FREE if not found."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT tier FROM subscriptions WHERE chat_jid = ?",
            (chat_jid,)
        )
        result = cur.fetchone()
        conn.close()
        
        if result:
            tier_str = result[0].lower()
            try:
                return SubscriptionTier(tier_str)
            except ValueError:
                return SubscriptionTier.FREE
        return SubscriptionTier.FREE
    except Exception as e:
        print(f"⚠️  Error getting subscription tier: {e}", flush=True)
        return SubscriptionTier.FREE


def set_subscription_tier(
    db_path: str,
    chat_jid: str,
    tier: SubscriptionTier,
    expires_at: Optional[datetime] = None,
    notes: Optional[str] = None
) -> bool:
    """Set or update subscription tier for a chat JID."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        expires_str = expires_at.isoformat() if expires_at else None
        
        cur.execute(
            """
            INSERT OR REPLACE INTO subscriptions 
            (chat_jid, tier, subscribed_at, expires_at, notes)
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
            """,
            (chat_jid, tier.value, expires_str, notes)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error setting subscription tier: {e}", flush=True)
        return False


def reset_daily_counts(db_path: str) -> None:
    """Reset daily message counts for all subscriptions (call this daily)."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE subscriptions 
            SET daily_message_count = 0, last_reset_date = CURRENT_DATE
            WHERE last_reset_date < CURRENT_DATE
            """
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️  Error resetting daily counts: {e}", flush=True)


def increment_daily_count(db_path: str, chat_jid: str) -> int:
    """Increment daily message count for a subscription. Returns new count."""
    try:
        # First, reset if needed
        reset_daily_counts(db_path)
        
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # Get current count and reset date
        cur.execute(
            "SELECT daily_message_count, last_reset_date FROM subscriptions WHERE chat_jid = ?",
            (chat_jid,)
        )
        result = cur.fetchone()
        
        if result:
            count, last_reset = result
            # Reset if it's a new day
            today = datetime.now().date()
            if last_reset and datetime.fromisoformat(last_reset).date() < today:
                count = 0
            
            new_count = count + 1
            cur.execute(
                """
                UPDATE subscriptions 
                SET daily_message_count = ?, last_reset_date = CURRENT_DATE
                WHERE chat_jid = ?
                """,
                (new_count, chat_jid)
            )
        else:
            # Create subscription record if doesn't exist
            new_count = 1
            cur.execute(
                """
                INSERT INTO subscriptions (chat_jid, tier, daily_message_count, last_reset_date)
                VALUES (?, 'free', ?, CURRENT_DATE)
                """,
                (chat_jid, new_count)
            )
        
        conn.commit()
        conn.close()
        return new_count
    except Exception as e:
        print(f"⚠️  Error incrementing daily count: {e}", flush=True)
        return 0


def can_process_message(db_path: str, chat_jid: str) -> Tuple[bool, Optional[str]]:
    """Check if a message can be processed based on subscription limits.
    
    Returns:
        Tuple of (can_process: bool, reason: Optional[str])
    """
    tier = get_subscription_tier(db_path, chat_jid)
    limits = TIER_LIMITS[tier]
    
    # Check daily message limit
    daily_limit = limits["daily_messages"]
    if daily_limit > 0:  # -1 means unlimited
        current_count = get_daily_count(db_path, chat_jid)
        if current_count >= daily_limit:
            return False, f"Daily limit reached ({daily_limit} messages). Upgrade to continue."
    
    # Check expiration (if subscription has expiration)
    if is_subscription_expired(db_path, chat_jid):
        return False, "Subscription has expired. Please renew."
    
    return True, None


def get_daily_count(db_path: str, chat_jid: str) -> int:
    """Get current daily message count for a subscription."""
    try:
        reset_daily_counts(db_path)  # Ensure counts are reset if needed
        
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT daily_message_count FROM subscriptions WHERE chat_jid = ?",
            (chat_jid,)
        )
        result = cur.fetchone()
        conn.close()
        
        return result[0] if result else 0
    except Exception as e:
        print(f"⚠️  Error getting daily count: {e}", flush=True)
        return 0


def is_subscription_expired(db_path: str, chat_jid: str) -> bool:
    """Check if subscription has expired."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT expires_at FROM subscriptions WHERE chat_jid = ?",
            (chat_jid,)
        )
        result = cur.fetchone()
        conn.close()
        
        if result and result[0]:
            expires_at = datetime.fromisoformat(result[0])
            return datetime.now() > expires_at
        return False  # No expiration = never expired
    except Exception as e:
        print(f"⚠️  Error checking expiration: {e}", flush=True)
        return False


def get_tier_info(tier: SubscriptionTier) -> Dict:
    """Get information about a subscription tier."""
    return TIER_LIMITS[tier].copy()


def can_transcribe_voice(db_path: str, chat_jid: str) -> bool:
    """Check if user can transcribe voice messages based on subscription."""
    tier = get_subscription_tier(db_path, chat_jid)
    limits = TIER_LIMITS[tier]
    return limits.get("voice_transcription", False)


def get_batch_window_override(db_path: str, chat_jid: str) -> Optional[int]:
    """Get batch window override for subscription tier. Returns None to use default."""
    tier = get_subscription_tier(db_path, chat_jid)
    limits = TIER_LIMITS[tier]
    return limits.get("batch_window_override", None)


def get_subscription_info(db_path: str, chat_jid: str) -> Dict:
    """Get full subscription information for a chat."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT tier, daily_message_count, last_reset_date, subscribed_at, expires_at, notes
            FROM subscriptions WHERE chat_jid = ?
            """,
            (chat_jid,)
        )
        result = cur.fetchone()
        conn.close()
        
        if result:
            tier_str, count, reset_date, sub_at, exp_at, notes = result
            tier = SubscriptionTier(tier_str.lower())
            limits = TIER_LIMITS[tier]
            
            return {
                "tier": tier.value,
                "daily_messages_used": count,
                "daily_messages_limit": limits["daily_messages"],
                "last_reset_date": reset_date,
                "subscribed_at": sub_at,
                "expires_at": exp_at,
                "is_expired": is_subscription_expired(db_path, chat_jid),
                "voice_transcription": limits["voice_transcription"],
                "priority_processing": limits["priority_processing"],
                "notes": notes,
            }
        else:
            # Default FREE tier
            tier = SubscriptionTier.FREE
            limits = TIER_LIMITS[tier]
            return {
                "tier": tier.value,
                "daily_messages_used": 0,
                "daily_messages_limit": limits["daily_messages"],
                "last_reset_date": None,
                "subscribed_at": None,
                "expires_at": None,
                "is_expired": False,
                "voice_transcription": limits["voice_transcription"],
                "priority_processing": limits["priority_processing"],
                "notes": None,
            }
    except Exception as e:
        print(f"⚠️  Error getting subscription info: {e}", flush=True)
        return {}

