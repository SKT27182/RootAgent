import requests
import uuid
import time
import sys

BASE_URL = "http://localhost:8000"

def test_health():
    print("Testing Health Endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        if response.status_code == 200:
            print("Health Check Passed:", response.json())
        else:
            print("Health Check Failed:", response.status_code, response.text)
            sys.exit(1)
    except Exception as e:
        print(f"Health Check Error: {e}")
        sys.exit(1)

def test_chat():
    print("\nTesting Chat Endpoint...")
    user_id = "test_user_1"
    session_id = str(uuid.uuid4())
    
    payload = {
        "query": "Hello, who are you?",
        "user_id": user_id,
        "session_id": session_id
    }
    
    try:
        response = requests.post(f"{BASE_URL}/chat", json=payload)
        if response.status_code == 200:
            data = response.json()
            print("Chat Response:", data)
            assert data["session_id"] == session_id
            assert "response" in data
        else:
            print("Chat Request Failed:", response.status_code, response.text)
            sys.exit(1)
            
        # Verify History
        print("\nVerifying History...")
        history_resp = requests.get(f"{BASE_URL}/chat/history/{user_id}/{session_id}")
        if history_resp.status_code == 200:
            history = history_resp.json()
            print(f"History retrieved: {len(history)} messages")
            for msg in history:
                print(f"- [{msg['role']}]: {msg['content']}")
        else:
             print("History Retrieval Failed:", history_resp.status_code, history_resp.text)

    except Exception as e:
        print(f"Chat Test Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Wait a bit for server to start if running in parallel (manual check required)
    time.sleep(2)
    test_health()
    test_chat()
