import asyncio
import uuid

from fastapi.testclient import TestClient

from app import main


app = main.app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "keys_configured" in response.json()
    assert response.json()["cache_enabled"] is True


def test_chat_and_history():
    response = client.post(
        "/chat",
        json={
            "session_id": "test-session",
            "message": "What is the capital of France?",
            "system_prompt": "Keep replies concise.",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "test-session"
    assert data["reply"]
    assert data["metadata"]["resolution_source"] in ("LIVE_INFERENCE", "LLM_CACHE")

    history = client.get("/sessions/test-session/messages")
    assert history.status_code == 200
    assert history.json()["system_prompt"] == "Keep replies concise."
    assert history.json()["messages"][0]["role"] == "user"
    assert history.json()["messages"][1]["role"] == "assistant"


def test_chat_can_clear_system_prompt(monkeypatch):
    async def fake_call_provider(model, messages, simulations):
        return "Test reply", "test-key", 0, 1, 1

    monkeypatch.setattr(main, "call_provider", fake_call_provider)
    session_id = f"clear-prompt-{uuid.uuid4().hex}"

    created = client.post(
        "/chat",
        json={
            "session_id": session_id,
            "message": "First message",
            "system_prompt": "Always be concise.",
        },
    )
    cleared = client.post(
        "/chat",
        json={
            "session_id": session_id,
            "message": "Second message",
            "system_prompt": "",
        },
    )

    assert created.status_code == 200
    assert cleared.status_code == 200
    history = client.get(f"/sessions/{session_id}/messages")
    assert history.json()["system_prompt"] == ""


def test_cache_across_sessions():
    first = client.post(
        "/chat",
        json={"session_id": "cache-one", "message": "A uniquely cached test prompt"},
    )
    second = client.post(
        "/chat",
        json={"session_id": "cache-two", "message": "A uniquely cached test prompt"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["reply"] == second.json()["reply"]
    assert second.json()["metadata"]["resolution_source"] == "LLM_CACHE"


def test_validation():
    response = client.post("/chat", json={"session_id": "", "message": ""})
    assert response.status_code == 422


def test_unknown_session():
    response = client.get("/sessions/does-not-exist/messages")
    assert response.status_code == 404
    assert response.json()["detail"] == "session not found"


def test_sessions_list_includes_conversation_title():
    session_id = f"list-session-{uuid.uuid4().hex}"
    title = f"Conversation title {uuid.uuid4().hex}"
    created = client.post(
        "/chat",
        json={"session_id": session_id, "message": title},
    )
    assert created.status_code == 200

    response = client.get("/sessions")

    assert response.status_code == 200
    session = next(item for item in response.json()["sessions"] if item["session_id"] == session_id)
    assert session["title"] == title
    assert session["updated_at"]


def test_groq_model_uses_only_groq_keys(monkeypatch):
    calls = []

    async def fake_completion(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "Groq reply"}}]}

    monkeypatch.setattr(
        main,
        "PROVIDER_KEYS",
        {
            "gemini": [("gemini_key_1", "gemini-secret")],
            "groq": [("groq_key_1", "groq-secret")],
        },
    )
    monkeypatch.setattr(main.litellm, "acompletion", fake_completion)

    result = asyncio.run(
        main.call_provider(
            "groq/openai/gpt-oss-20b",
            [{"role": "user", "content": "Hello"}],
            {},
        )
    )

    assert calls[0]["api_key"] == "groq-secret"
    assert result[1] == "groq_key_1"


def test_groq_model_does_not_fall_back_to_gemini_key(monkeypatch):
    monkeypatch.setattr(
        main,
        "PROVIDER_KEYS",
        {"gemini": [("gemini_key_1", "gemini-secret")], "groq": []},
    )
    monkeypatch.setattr(main, "KEYS", [("gemini_key_1", "gemini-secret")])

    response = client.post(
        "/chat",
        json={
            "session_id": "missing-groq-key",
            "message": "Hello",
            "model": "groq/openai/gpt-oss-20b",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "No GROQ_API_KEYS configured for the selected model."
