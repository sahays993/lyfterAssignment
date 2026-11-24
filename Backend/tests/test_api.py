from fastapi.testclient import TestClient

from app.main import app


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
        json={"session_id": "test-session", "message": "What is the capital of France?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "test-session"
    assert data["reply"]
    assert data["metadata"]["resolution_source"] in ("LIVE_INFERENCE", "LLM_CACHE")

    history = client.get("/sessions/test-session/messages")
    assert history.status_code == 200
    assert history.json()["messages"][0]["role"] == "user"
    assert history.json()["messages"][1]["role"] == "assistant"


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
