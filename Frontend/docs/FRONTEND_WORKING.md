# Frontend Working

## Overview

The frontend is a React single-page app built with Vite. Its entry point is `src/main.jsx`; visual styles, responsive layout, and light/dark theme colors are in `src/styles.css`. The app connects to the FastAPI backend and renders the conversation and per-reply metadata.

## Start the frontend

Install dependencies and start the Vite development server:

```bash
pnpm install
pnpm dev
```

Vite listens on port `5173`. The API base URL is read from `VITE_API_URL`; if it is unset, the frontend uses `http://localhost:8000`.

## Startup and backend status

When the app loads, it creates a new session ID in the browser and requests `GET {API_URL}/health`. The connection indicator reflects whether that request succeeds. Conversation state starts empty; reloading the page creates a new session rather than restoring previous messages from the browser.

## Sending a message

1. The user types in the composer and submits with the send button or Enter. Shift+Enter inserts a line break. Enter does not submit while a CJK IME composition is in progress.
2. The frontend trims the message, shows it immediately in the conversation, and disables sending while the request is pending.
3. It sends `POST {API_URL}/chat` as JSON with `session_id`, `message`, the selected `model`, and optional context fields and `system_prompt`.
4. A successful response adds the assistant reply and metadata to the conversation. Metadata shown per reply includes resolution source, model, latency, and input/output tokens.
5. An unsuccessful response or network failure is shown as an inline error message; the connection indicator is set to offline. The input can be submitted again after the request completes.

The model menu offers Gemini 2.0 Flash, GPT-4o mini, and Qwen3 0.6B. The selected model ID is sent in the request; the backend must honor that `model` field and have the corresponding provider/model configured for the choice to change inference. The frontend alone cannot install or run a local Ollama model.

## Context attachments

The plus menu supports PDF files and URLs:

- **PDFs:** The frontend accepts PDF files up to 10 MB and extracts selectable text using `pdfjs-dist` in the browser. It sends up to 50,000 characters of extracted text per file as part of the request's system prompt. Image-only/scanned PDFs have no extractable text and are not OCR-processed.
- **Links:** The user can attach an `http` or `https` URL. The URL is included in the system prompt as a reference and also sent in the extra `context_links` request field. The browser does not fetch the webpage. To use the page contents, the backend must support `context_links` and safely retrieve/process those URLs.
- Attachment chips can be removed before sending. Starting a new chat clears the attachments.

The core API contract described in the assignment does not define `model` or `context_links`. If the backend ignores extra request fields, model switching and link context will not work until the backend is updated to handle them. PDF text is carried through the optional `system_prompt` field.

## Other UI behavior

- The optional system prompt is editable from the “Context aware” control and is combined with attached PDF text and URL references for each request.
- “New chat” creates a fresh session ID and clears messages, the composer text, and attachments. The currently selected model, theme, and system prompt remain selected in the active page.
- The theme control switches between light and matte-black dark styles. The selection is held in React state and resets on page reload.
- Reply actions copy assistant text to the clipboard. The welcome cards fill the composer with a suggested prompt.

## Main dependencies

- `react` and `react-dom` render the interface and manage its state.
- `vite` serves and bundles the frontend.
- `lucide-react` provides interface icons.
- `pdfjs-dist` extracts text from attached PDF files.
