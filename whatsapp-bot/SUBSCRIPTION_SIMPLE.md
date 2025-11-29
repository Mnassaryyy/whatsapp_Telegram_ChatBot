# Simple Subscription System

A simple 3-tier tagging system that displays subscription tiers on Telegram message cards.

## 🎯 Purpose

Tag users with subscription tiers and display them on Telegram approval cards. **No feature restrictions** - all users get the same features regardless of tier.

## 📊 Subscription Tiers

- **🆓 FREE** - Default tier for all users
- **🥉 BASIC** - Basic subscription tier  
- **💎 PREMIUM** - Premium subscription tier

## 📱 Display on Telegram

When messages arrive on Telegram, they show:

```
🔔 New WhatsApp Message

👤 From: John Doe
📱 Number: 1234567890@s.whatsapp.net
🎯 Subscription: 💎 PREMIUM
🕒 Received: 2h ago

💬 Message:
Hello...

🤖 AI Suggested Reply:
Hi there...
```

## 🔧 Commands

### Set Subscription Tier

```
/set_tier <phone_or_jid> <tier>
```

**Examples:**
```
/set_tier 1234567890 premium
/set_tier 1234567890 basic
/set_tier 1234567890@s.whatsapp.net free
```

### View Subscription

```
/subscription <phone_or_jid>
```

**Example:**
```
/subscription 1234567890
```

## 💾 How It Works

1. **Tagging**: Users are tagged with a tier (free/basic/premium)
2. **Storage**: Stored in `subscriptions` table in database
3. **Display**: Tier is automatically shown on Telegram cards when messages arrive
4. **No Restrictions**: All tiers have the same features and limits

## 📝 Default Behavior

- New users default to **FREE** tier
- Tiers can be changed anytime with `/set_tier`
- Tier display is automatic on all Telegram message cards

## 🎨 Tier Emojis

- 🆓 FREE
- 🥉 BASIC  
- 💎 PREMIUM

