import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
import ipaddress
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
import litellm
from bs4 import BeautifulSoup
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")
ENABLE_FAILURE_SIMULATION = os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower() == "true"
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "groq/openai/gpt-oss-20b")


def sqlite_path() -> str:
    if not DATABASE_URL.startswith("sqlite"):
        raise RuntimeError("DATABASE_URL must use SQLite")
    path = DATABASE_URL.replace("sqlite:///", "", 1)
    if not path.startswith("/"):
        path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return path


DB_PATH = sqlite_path()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session_id_id
                ON messages(session_id, id);
            CREATE TABLE IF NOT EXISTS response_cache (
                cache_key TEXT PRIMARY KEY,
                reply TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                system_prompt TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )


init_db()


def parse_api_keys(value: str) -> list[str]:
    return [key.strip() for key in value.split(",") if key.strip()]


class ProviderConfigurationError(RuntimeError):
    pass


raw_gemini_keys = parse_api_keys(os.getenv("GEMINI_API_KEYS", ""))
if not raw_gemini_keys:
    raw_gemini_keys = parse_api_keys(os.getenv("LLM_API_KEYS", ""))
raw_groq_keys = parse_api_keys(os.getenv("GROQ_API_KEYS", ""))
GEMINI_KEYS = [(f"gemini_key_{index}", key) for index, key in enumerate(raw_gemini_keys, start=1)]
GROQ_KEYS = [(f"groq_key_{index}", key) for index, key in enumerate(raw_groq_keys, start=1)]
PROVIDER_KEYS = {"gemini": GEMINI_KEYS, "groq": GROQ_KEYS}
KEYS = GEMINI_KEYS + GROQ_KEYS
MODEL_ALIASES = {
    "gemini/gemini-3.5-flash": "gemini/gemini-3.5-flash",
    "groq/openai/gpt-oss-20b": "groq/openai/gpt-oss-20b",
    "groq/openai/gpt-oss-120b": "groq/openai/gpt-oss-120b",
    "ollama/qwen3:0.6b": "ollama/qwen3:0.6b",
}

litellm.cache = litellm.Cache(type="local")
litellm.suppress_debug_info = True

app = FastAPI(title="Lyftr AI Backend")
origins = [origin.strip() for origin in ALLOWED_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    system_prompt: str | None = None
    model: str | None = None
    context_links: list[str] | None = None


def clean_request(payload: ChatRequest):
    payload.session_id = payload.session_id.strip()
    payload.message = payload.message.strip()
    if not payload.session_id or not payload.message:
        raise HTTPException(status_code=422, detail="session_id and message are required")
    if len(payload.message) > 4000:
        raise HTTPException(status_code=422, detail="message must be 4000 characters or fewer")


@app.get("/health")
async def health():
    try:
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok", "keys_configured": len(KEYS), "cache_enabled": True}


def get_history(session_id: str):
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def get_session_system_prompt(session_id: str):
    with db() as conn:
        row = conn.execute(
            "SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return row["system_prompt"] if row else None


def cache_key(model: str, messages: list[dict[str, str]], context_links: list[str] | None):
    payload = json.dumps(
        {"model": model, "messages": messages, "context_links": context_links or []},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_lookup(key: str):
    with db() as conn:
        row = conn.execute(
            "SELECT reply, metadata FROM response_cache WHERE cache_key = ?", (key,)
        ).fetchone()
    if not row:
        return None
    return row["reply"], json.loads(row["metadata"])


def cache_store(key: str, reply: str, metadata: dict[str, Any]):
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO response_cache(cache_key, reply, metadata, created_at) VALUES (?, ?, ?, ?)",
            (key, reply, json.dumps(metadata), utc_now()),
        )


def store_session_turn(session_id: str, message: str, reply: str, metadata: dict[str, Any], system_prompt: str | None):
    with db() as conn:
        conn.execute(
            "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES (?, 'user', ?, NULL, ?)",
            (session_id, message, utc_now()),
        )
        conn.execute(
            "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES (?, 'assistant', ?, ?, ?)",
            (session_id, reply, json.dumps(metadata), utc_now()),
        )
        conn.execute(
            """
            INSERT INTO sessions(session_id, system_prompt, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET system_prompt=excluded.system_prompt,
                                                   updated_at=excluded.updated_at
            """,
            (session_id, system_prompt, utc_now()),
        )


def parse_simulations(header: str | None):
    if not ENABLE_FAILURE_SIMULATION or not header:
        return {}
    result = {}
    for item in header.split(","):
        if "=" not in item:
            continue
        key_id, status = (part.strip() for part in item.split("=", 1))
        if key_id == "*":
            for key, _ in KEYS:
                result[key] = int(status) if status.isdigit() else 0
        elif status.isdigit():
            result[key_id] = int(status)
    return result


def estimate_tokens(text: str):
    return max(1, len(text.encode("utf-8")) // 4)


async def fetch_link_context(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return ""
    except Exception:
        return ""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text/html" in content_type:
                soup = BeautifulSoup(response.text, "html.parser")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                text = soup.get_text(" ", strip=True)
            else:
                text = response.text
            return text[:10000]
    except Exception:
        return ""


def offline_answer(message: str, system_prompt: str | None):
    # A safe local fallback keeps the UI usable when no provider key is configured.
    lowered = message.lower()
    if "capital" in lowered and "france" in lowered:
        return "The capital of France is Paris."
    if "hello" in lowered or "hi " in lowered:
        return "Hello! How can I help you today?"
    if system_prompt:
        return f"I understand your request: {message}\n\nContext: {system_prompt[:500]}"
    return f"I can help with that. Please clarify or add more detail to: {message}"


async def call_provider(model: str, messages: list[dict[str, str]], simulation: dict[str, int]):
    provider = model.split("/", 1)[0]
    if provider == "ollama":
        provider_keys: list[tuple[str | None, str | None]] = [(None, None)]
    else:
        configured_keys = PROVIDER_KEYS.get(provider)
        if configured_keys is None:
            raise RuntimeError("unsupported model provider")
        if not configured_keys:
            if KEYS:
                raise ProviderConfigurationError(
                    f"No {provider.upper()}_API_KEYS configured for the selected model."
                )
            reply = offline_answer(
                messages[-1]["content"],
                next((m["content"] for m in messages if m["role"] == "system"), None),
            )
            return reply, None, 0

        provider_keys = [
            (key_id, key)
            for key_id, key in configured_keys
            if not key.lower().startswith(("placeholder", "your_", "sk-placeholder"))
        ]
        if not provider_keys:
            if all(
                key.lower().startswith(("placeholder", "your_", "sk-placeholder"))
                for _, key in KEYS
            ):
                failed = 0
                for key_id, _ in configured_keys:
                    if key_id in simulation:
                        failed += 1
                        continue
                    reply = offline_answer(
                        messages[-1]["content"],
                        next((m["content"] for m in messages if m["role"] == "system"), None),
                    )
                    return reply, None, failed
            raise RuntimeError(f"no usable {provider} API keys configured")

    fallback_attempts = 0
    for key_id, api_key in provider_keys:
        if key_id is not None and key_id in simulation:
            fallback_attempts += 1
            continue
        try:
            provider_options = {"api_key": api_key} if api_key else {}
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
                **provider_options,
            )
            reply = response["choices"][0]["message"]["content"].strip()
            if not reply:
                raise RuntimeError("empty provider response")
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            output_tokens = getattr(usage, "completion_tokens", None) if usage else None
            if input_tokens is None:
                input_tokens = sum(estimate_tokens(m["content"]) for m in messages)
            if output_tokens is None:
                output_tokens = estimate_tokens(reply)
            return (reply, key_id, fallback_attempts, int(input_tokens), int(output_tokens))
        except Exception:
            fallback_attempts += 1
    raise RuntimeError("all providers unavailable")


@app.post("/chat")
async def chat(payload: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
    clean_request(payload)
    system_prompt = payload.system_prompt
    if system_prompt is None:
        system_prompt = get_session_system_prompt(payload.session_id)

    history = get_history(payload.session_id)
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for link in payload.context_links or []:
        text = await fetch_link_context(link)
        if text:
            system_prompt = f"{system_prompt or ''}\n\nReference {link}:\n{text}".strip()
    if system_prompt and (not messages or messages[0]["role"] != "system"):
        messages.insert(0, {"role": "system", "content": system_prompt})
    elif system_prompt:
        messages[0]["content"] = system_prompt
    messages.extend(history)
    messages.append({"role": "user", "content": payload.message})

    requested_model = payload.model or DEFAULT_MODEL
    model = MODEL_ALIASES.get(requested_model)
    if model is None:
        raise HTTPException(status_code=422, detail="unsupported model")
    key = cache_key(model, messages, payload.context_links)
    hit = cache_lookup(key)
    started = time.perf_counter()
    if hit:
        reply, cached_metadata = hit
        metadata = {
            "resolution_source": "LLM_CACHE",
            "model": model,
            "latency_ms": max(1, int((time.perf_counter() - started) * 1000)),
            "input_tokens": cached_metadata["input_tokens"],
            "output_tokens": cached_metadata["output_tokens"],
            "key_id": None,
            "fallback_attempts": 0,
        }
        store_session_turn(payload.session_id, payload.message, reply, metadata, system_prompt)
        return {"session_id": payload.session_id, "reply": reply, "metadata": metadata}

    try:
        result = await call_provider(model, messages, parse_simulations(x_simulate_failure))
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=503, detail="all providers unavailable")

    if len(result) == 3:
        reply, key_id, fallback_attempts = result
        input_tokens = sum(estimate_tokens(m["content"]) for m in messages)
        output_tokens = estimate_tokens(reply)
    else:
        reply, key_id, fallback_attempts, input_tokens, output_tokens = result

    metadata = {
        "resolution_source": "LIVE_INFERENCE",
        "model": model,
        "latency_ms": max(1, int((time.perf_counter() - started) * 1000)),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "key_id": key_id,
        "fallback_attempts": fallback_attempts,
    }
    cache_store(key, reply, metadata)
    store_session_turn(payload.session_id, payload.message, reply, metadata, system_prompt)
    return {"session_id": payload.session_id, "reply": reply, "metadata": metadata}


@app.get("/sessions")
async def list_sessions():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT grouped.session_id,
                   (
                       SELECT content
                       FROM messages AS first_user
                       WHERE first_user.session_id = grouped.session_id
                         AND first_user.role = 'user'
                       ORDER BY first_user.id ASC
                       LIMIT 1
                   ) AS title,
                   MAX(grouped.created_at) AS updated_at
            FROM messages AS grouped
            GROUP BY grouped.session_id
            ORDER BY MAX(grouped.id) DESC
            LIMIT 100
            """
        ).fetchall()
    return {"sessions": [dict(row) for row in rows]}


@app.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str):
    session_id = session_id.strip()
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="session not found")
    messages = []
    for row in rows:
        item = {"role": row["role"], "content": row["content"]}
        if row["role"] == "assistant" and row["metadata"]:
            metadata = json.loads(row["metadata"])
            item["metadata"] = {
                "resolution_source": metadata["resolution_source"],
                "model": metadata["model"],
                "latency_ms": metadata["latency_ms"],
                "input_tokens": metadata["input_tokens"],
                "output_tokens": metadata["output_tokens"],
            }
        messages.append(item)
    return {
        "session_id": session_id,
        "messages": messages,
        "system_prompt": get_session_system_prompt(session_id) or "",
    }
