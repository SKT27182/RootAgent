import sys
import os
import uuid
from fastapi.testclient import TestClient

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.main import app

client = TestClient(app)


def test_chat_persistence():
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    session_id = f"session_{uuid.uuid4().hex[:8]}"

    print(f"Testing with User ID: {user_id}, Session ID: {session_id}")

    # 1. Send first message
    print("\n[1] Sending first message: 'My name is Antigravity'")
    response1 = client.post(
        "/chat",
        json={
            "query": "My name is Antigravity",
            "user_id": user_id,
            "session_id": session_id,
            "images": [],
        },
    )

    if response1.status_code != 200:
        print(f"FAILED: Step 1 failed with status {response1.status_code}")
        print(response1.text)
        return

    print(f"Response 1: {response1.json()['response']}")

    # 2. Send second message
    print("\n[2] Sending second message: 'What is my name?'")
    response2 = client.post(
        "/chat",
        json={
            "query": "What is my name?",
            "user_id": user_id,
            "session_id": session_id,
            "images": [],
        },
    )

    if response2.status_code != 200:
        print(f"FAILED: Step 2 failed with status {response2.status_code}")
        print(response2.text)
        return

    reply = response2.json()["response"]
    print(f"Response 2: {reply}")

    if "Antigravity" in reply:
        print("\nSUCCESS: Context was preserved!")
    else:
        print("\nFAILED: Context was NOT preserved.")


if __name__ == "__main__":
    test_chat_persistence()
