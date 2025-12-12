import asyncio
import websockets
import json
import uuid


async def test_ws_chat():
    uri = "ws://localhost:8000/chat/ws"
    session_id = str(uuid.uuid4())
    user_id = "test_user_ws"

    payload = {
        "query": "Count from 1 to 5",
        "user_id": user_id,
        "session_id": session_id,
        "include_reasoning": True,
    }

    try:
        async with websockets.connect(uri) as websocket:
            print(f"Connected to {uri}")
            await websocket.send(json.dumps(payload))
            print("Sent payload.")

            while True:
                try:
                    message = await websocket.recv()
                    data = json.loads(message)
                    event_type = data.get("type", "unknown")
                    content = data.get("content", "")

                    if event_type == "token":
                        print(f"[TOKEN] {content}", end="", flush=True)
                    elif event_type == "tool_output":
                        print(f"\n[TOOL] {content}")
                    elif event_type == "info":
                        print(f"\n[INFO] {content}")
                    elif event_type == "error":
                        print(f"\n[ERROR] {content}")
                        break
                    elif event_type == "final":
                        print(f"\n[FINAL] {content}")
                        break

                except websockets.exceptions.ConnectionClosed:
                    print("\nConnection closed.")
                    break
    except Exception as e:
        print(f"Test failed: {e}")


if __name__ == "__main__":
    asyncio.run(test_ws_chat())
