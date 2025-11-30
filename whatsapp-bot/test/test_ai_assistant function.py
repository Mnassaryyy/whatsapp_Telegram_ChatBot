"""Test script for OpenAI Assistants API integration.

This script imports and tests the _generate_ai_reply_assistants function from ai_utils.py
"""

import os
from openai import OpenAI
from helpers.ai_utils import _generate_ai_reply_assistants
# Import the function from your ai_utils module

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")


class MockBot:
    """Mock bot object for testing."""

    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self._assistant_threads = {}


def test_assistant():
    """Test the assistant function with sample messages."""

    print("=" * 60)
    print("Testing OpenAI Assistants API Integration")
    print("=" * 60)

    # Validate configuration
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY not found in .env file")
        return

    if not OPENAI_ASSISTANT_ID:
        print("❌ OPENAI_ASSISTANT_ID not found in .env file")
        return

    print(f"✅ API Key found: {OPENAI_API_KEY[:20]}...")
    print(f"✅ Assistant ID: {OPENAI_ASSISTANT_ID}")
    print()

    # Create mock bot
    bot = MockBot()

    # Test chat JID (simulating a WhatsApp chat)
    test_jid = "test_user_123@s.whatsapp.net"

    # Test 1: First message
    print("\n" + "=" * 60)
    print("TEST 1: First message in conversation")
    print("=" * 60)
    response1 = _generate_ai_reply_assistants(
        bot,
        test_jid,
        "Hello! Can you introduce yourself?",
        OPENAI_ASSISTANT_ID
    )

    if response1:
        print(f"\n📤 Response:\n{response1}\n")
    else:
        print("\n❌ No response received\n")

    # Test 2: Follow-up message (should use same thread)
    print("\n" + "=" * 60)
    print("TEST 2: Follow-up message (same thread)")
    print("=" * 60)
    response2 = _generate_ai_reply_assistants(
        bot,
        test_jid,
        "What was my previous question?",
        OPENAI_ASSISTANT_ID
    )

    if response2:
        print(f"\n📤 Response:\n{response2}\n")
    else:
        print("\n❌ No response received\n")

    # Test 3: Different chat (should create new thread)
    print("\n" + "=" * 60)
    print("TEST 3: Different chat (new thread)")
    print("=" * 60)
    different_jid = "different_user_456@s.whatsapp.net"
    response3 = _generate_ai_reply_assistants(
        bot,
        different_jid,
        "Hi, this is a different conversation!",
        OPENAI_ASSISTANT_ID
    )

    if response3:
        print(f"\n📤 Response:\n{response3}\n")
    else:
        print("\n❌ No response received\n")

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total threads created: {len(bot._assistant_threads)}")
    print(f"Thread mapping: {bot._assistant_threads}")
    print("\n✅ Testing complete!")


if __name__ == "__main__":
    test_assistant()