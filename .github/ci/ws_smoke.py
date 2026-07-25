"""Authenticate and verify the ticketed WebSocket path through the central proxy."""

import asyncio
import json
import urllib.parse
import urllib.request

import websockets


BASE_URL = "http://127.0.0.1:18080"


def request(path: str, data: bytes, content_type: str, token: str | None = None) -> dict:
    headers = {"Content-Type": content_type}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    value = urllib.request.urlopen(
        urllib.request.Request(BASE_URL + path, data=data, headers=headers), timeout=10
    ).read()
    return json.loads(value)


async def main() -> None:
    credentials = {"email": "smoke@example.com", "name": "Smoke", "password": "smoke-pass-123"}
    request("/auth/register", json.dumps(credentials).encode(), "application/json")
    login = request(
        "/auth/login",
        urllib.parse.urlencode(
            {"username": credentials["email"], "password": credentials["password"]}
        ).encode(),
        "application/x-www-form-urlencoded",
    )
    token = login["access_token"]
    ticket = request("/auth/ws-ticket", b"", "application/json", token)["ticket"]
    async with websockets.connect(
        f"ws://127.0.0.1:18080/chat/ws?ticket={ticket}",
        origin="https://rootagent.local",
    ) as socket:
        await socket.send("not-json")
        event = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
        assert event["type"] == "error"
        assert event["code"] == "invalid_request"


if __name__ == "__main__":
    asyncio.run(main())
