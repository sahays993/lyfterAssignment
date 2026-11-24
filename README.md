# Lyftr AI Chat

## 1. Live URLs
- Frontend:
- Backend:

## 2. Run locally: with Docker and without

Docker:
```sh
make up
```
Open http://localhost:3000. The API runs at http://localhost:8000.

Without Docker:
```sh
cd Backend
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --reload --port 8000

cd ../Frontend
pnpm install
pnpm dev
```

## 3. Design decisions: key fallback, caching, SQLite session storage

FastAPI stores all accepted turns and assistant metadata in SQLite. The database path is controlled by `DATABASE_URL`, and Docker mounts `/data` on a named volume. LiteLLM performs provider calls and local response caching; an additional SQLite cache guarantees identical first messages are cached across sessions.

The backend iterates `LLM_API_KEYS` in order, sends a failure status to the next key on 429, quota, or 5xx responses, and records fallback attempts. Cached responses do not call a provider.

## 4. Verification: how to see failover, cache hits and per-message token usage

Health:
```sh
curl http://localhost:8000/health
```

Chat:
```sh
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo","message":"What is the capital of France?"}'
```

Failover:
```sh
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id":"demo2","message":"Explain caching"}'
```

Every reply includes per-request input and output token counts. Repeat the same model and complete message list to receive `LLM_CACHE`.

## 5. Setup Used: your editor and AI tools

Built in VS Code with Python, FastAPI, LiteLLM, SQLite, Docker Compose, React, and Vite.

## 6. Bonus features (if any): what you added beyond the requirements and why

- Safe URL context extraction for `context_links`.
- Provider/model selection for Gemini, GPT-4o mini, and Ollama.
- Per-session system prompts and attached PDF context support.
