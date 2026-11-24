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

## 3. Design decisions: provider keys, response caching, browser-local history

Conversation history is stored in the browser's local storage, so it remains on that browser and does not sync across devices. The backend accepts client-supplied conversation context for inference but does not expose session-list/history endpoints or save new conversation turns. The SQLite response cache is scoped to a random session ID.

Configure Gemini and Groq credentials separately with comma-separated `GEMINI_API_KEYS` and `GROQ_API_KEYS` values. The legacy `LLM_API_KEYS` variable is accepted as Gemini keys only. Each selected model uses only keys for its provider, and retries/failover stay within that provider.

The model picker includes Gemini 3.5 Flash and Groq-hosted GPT-OSS 20B/120B models. Cached responses do not call a provider.

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
  -H "X-Simulate-Failure: gemini_key_1=429" \
  -d '{"session_id":"demo2","message":"Explain caching"}'
```

Every reply includes per-request input and output token counts. Repeat the same model and complete message list to receive `LLM_CACHE`.

## 5. Setup Used: your editor and AI tools

Built in VS Code with Python, FastAPI, LiteLLM, SQLite, Docker Compose, React, and Vite.

## 6. Bonus features (if any): what you added beyond the requirements and why

- Safe URL context extraction for `context_links`.
- Provider/model selection for Gemini, Groq, and Ollama.
- Per-session system prompts and attached PDF context support.
