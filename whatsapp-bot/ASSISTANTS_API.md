# OpenAI Assistants API Integration

This document explains how to use OpenAI's Assistants API (thread-based) with the WhatsApp bot, and how it relates to the Chat Completions API approach.

## Overview

The bot now supports **two modes** for generating AI replies:

1. **Chat Completions API** (default) - The original method
   - Manual context building from SQLite database
   - Simple request/response pattern
   - Good for: Quick responses, full control over context

2. **Assistants API** - Thread-based conversations
   - Built-in thread/conversation management
   - Persistent context without manual history building
   - Good for: Complex conversations, tool/function calling

## How It Works

### Chat Completions Mode (Default)

```python
# In helpers/ai_utils.py - generate_ai_reply()
context_messages = _build_context_messages(bot, sender_jid, bot.MAX_CONVERSATION_HISTORY)
response = bot.client.chat.completions.create(model=OPENAI_MODEL, messages=context_messages)
return response.choices[0].message.content
```

**Flow:**
1. Builds conversation context from SQLite database
2. Sends entire context + new message to OpenAI
3. Gets reply immediately

### Assistants API Mode

Based on the `assistant_upgrade_position` pattern:

```python
# In helpers/ai_utils.py - _generate_ai_reply_assistants()
# Step 1: Get or create thread for this chat
thread_id = bot._assistant_threads.get(sender_jid)
if not thread_id:
    thread = bot.client.beta.threads.create()
    thread_id = thread.id
    bot._assistant_threads[sender_jid] = thread_id

# Step 2: Add user message to thread
bot.client.beta.threads.messages.create(thread_id=thread_id, role="user", content=message_text)

# Step 3: Run assistant
run = bot.client.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)

# Step 4: Wait for completion
while run_status.status != "completed":
    run_status = bot.client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
    time.sleep(1)

# Step 5: Get assistant's reply
messages = bot.client.beta.threads.messages.list(thread_id=thread_id)
```

**Flow:**
1. Maintains a thread per WhatsApp chat (using `sender_jid` as identifier)
2. Adds messages to the thread
3. Runs the assistant on the thread
4. Waits for completion and retrieves response

## Configuration

### Switch to Assistants API Mode

Add to your `.env` file:

```env
# Use Assistants API instead of Chat Completions
OPENAI_API_MODE=assistants
OPENAI_ASSISTANT_ID=asst_xxxxxxxxxxxxx  # Your Assistant ID from OpenAI
```

### Stay with Chat Completions (Default)

```env
OPENAI_API_MODE=chat
# or simply omit these variables
```

## Creating an OpenAI Assistant

1. Go to: https://platform.openai.com/assistants
2. Click "Create Assistant"
3. Configure:
   - **Name**: e.g., "WhatsApp Medical Assistant"
   - **Model**: e.g., "gpt-4" or "gpt-4-turbo"
   - **Instructions**: Your system prompt (same as `AI_SYSTEM_PROMPT`)
   - **Tools**: (Optional) Add function calling, code interpreter, etc.
4. Copy the Assistant ID (starts with `asst_...`)
5. Add it to your `.env` file

## Key Differences

| Feature | Chat Completions | Assistants API |
|---------|-----------------|----------------|
| Context Management | Manual (from SQLite) | Automatic (threads) |
| History Building | Bot builds from DB | OpenAI maintains |
| Tool Support | Limited | Full (functions, code, etc.) |
| Response Speed | Instant | Slight delay (run polling) |
| Thread Persistence | None | Per chat thread |
| Cost | Pay per token | Pay per token + thread storage |

## When to Use Each

### Use Chat Completions when:
- ✅ You want full control over conversation context
- ✅ Quick response time is critical
- ✅ You prefer simple request/response
- ✅ You want to minimize OpenAI API complexity

### Use Assistants API when:
- ✅ You want built-in conversation management
- ✅ You need tool/function calling capabilities
- ✅ You want OpenAI to manage conversation state
- ✅ You're building complex multi-turn workflows

## Thread Management

In Assistants mode, each WhatsApp chat gets its own thread:
- Thread ID is stored in `bot._assistant_threads[sender_jid]`
- Thread persists across bot restarts (stored in memory)
- One thread = one conversation history

**Note:** Threads are currently stored in memory. To persist across bot restarts, you could:
- Store thread IDs in SQLite database
- Use a mapping file
- Or let them expire (OpenAI manages thread lifecycle)

## Example: Your Code Integration

Your `assistant_upgrade_position` method:

```python
def assistant_upgrade_position(self, user_message, assistant_id):
    # Creates a new thread each time
    thread = self.client.beta.threads.create()
    # ... rest of your code
```

Integrated version:

```python
def _generate_ai_reply_assistants(bot, sender_jid, message_text, assistant_id):
    # Reuses thread per chat (sender_jid)
    thread_id = bot._assistant_threads.get(sender_jid)
    if not thread_id:
        thread = bot.client.beta.threads.create()
        thread_id = thread.id
        bot._assistant_threads[sender_jid] = thread_id
    # ... rest similar to your code
```

**Key improvement:** Threads are reused per chat, so conversation history persists!

## Troubleshooting

### Error: "OPENAI_ASSISTANT_ID is required"
- Make sure `OPENAI_ASSISTANT_ID` is set in `.env`
- Verify the Assistant ID is correct (starts with `asst_`)

### Assistant run fails or times out
- Check your Assistant configuration in OpenAI dashboard
- Verify you have sufficient API quota
- Check logs for specific error messages

### Threads not persisting across restarts
- This is expected - threads are in-memory
- Consider storing thread IDs in database for persistence
- Or recreate threads (OpenAI will maintain conversation context)

## Migration Guide

### From Chat Completions to Assistants API

1. Create an OpenAI Assistant (see above)
2. Add to `.env`:
   ```env
   OPENAI_API_MODE=assistants
   OPENAI_ASSISTANT_ID=asst_xxxxx
   ```
3. Restart the bot
4. Test with a message - thread will be created automatically

### From Assistants API to Chat Completions

1. Remove or change in `.env`:
   ```env
   OPENAI_API_MODE=chat
   ```
2. Restart the bot
3. Bot will use SQLite database for context instead

