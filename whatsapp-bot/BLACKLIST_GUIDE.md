# Blacklist/Block Feature Guide

Block users so their messages don't appear on Telegram.

## 🚫 How It Works

When you block a user:
1. **Current message**: Automatically removed from queue
2. **Future messages**: Automatically filtered and skipped
3. **No notifications**: You won't receive any messages from blocked users

## 🔘 Block Button

Every Telegram message card now has a **🚫 Block User** button at the bottom.

When clicked:
- User is immediately added to blacklist
- Current message is removed from queue
- Bot moves to next message
- Future messages from that user are automatically filtered

## 📋 Commands

### View Blacklist

```
/blacklist
```

Shows all currently blacklisted users with:
- Phone number
- Block date
- Reason (if set)

### Unblock User

```
/unblock <phone_or_jid>
```

**Examples:**
```
/unblock 1234567890
/unblock 1234567890@s.whatsapp.net
```

Removes user from blacklist. Messages from that user will be processed normally again.

## 🔄 Automatic Filtering

Blocked users are automatically filtered at the message processing stage:

```
🚫 Skipping message from blacklisted user: [phone/name]
```

Messages from blacklisted users:
- ❌ Not processed
- ❌ Not sent to Telegram
- ❌ Not queued
- ❌ No AI replies generated

## 💾 Database

Blacklisted users are stored in the `blacklist` table:

- `chat_jid`: User's WhatsApp JID (phone@s.whatsapp.net)
- `blocked_at`: Timestamp when blocked
- `reason`: Optional reason for blocking
- `notes`: Optional notes

## 📝 Usage Examples

### Block from Telegram Card

1. Message arrives on Telegram
2. Click **🚫 Block User** button
3. User is immediately blocked
4. Bot confirms and moves to next message

### Block via Command (Future)

You can manually add users to blacklist via code if needed:
```python
blacklist_utils.add_to_blacklist(db_path, chat_jid, reason="Spam")
```

## ⚠️ Notes

- Blocking is permanent until manually unblocked
- Blocked users can still send messages on WhatsApp (just won't reach you)
- Use `/blacklist` to see who is blocked
- Use `/unblock` to restore access

