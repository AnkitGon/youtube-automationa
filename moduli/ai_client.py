import os
import requests

# ── service routing ───────────────────────────────────────────────────────────
# Set AI_SERVICE in .env: openrouter | ollama_cloud | ollama_local
AI_SERVICE = os.environ.get("AI_SERVICE", "ollama_cloud")

# ── OLLAMA CLOUD ──────────────────────────────────────────────────────────────
OLLAMA_CLOUD_URL   = "https://ollama.com/api/chat"
OLLAMA_CLOUD_MODEL = "nemotron-3-super:cloud"

# ── OLLAMA LOCAL ──────────────────────────────────────────────────────────────
OLLAMA_LOCAL_URL   = "http://localhost:11434/api/chat"
OLLAMA_LOCAL_MODEL = os.environ.get("OLLAMA_LOCAL_MODEL", "llama3.2")

# ── OPENROUTER ────────────────────────────────────────────────────────────────
OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct:free"


def _ollama_cloud(messages: list, max_tokens: int = 8192) -> str:
    api_key = os.environ.get("OLLAMA_API_KEY", "")
    resp = requests.post(
        OLLAMA_CLOUD_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": OLLAMA_CLOUD_MODEL, "messages": messages, "stream": False,
              "think": False, "options": {"num_predict": max_tokens}},
        timeout=300,
    )
    resp.raise_for_status()
    msg = resp.json().get("message", {})
    content = msg.get("content", "") or msg.get("thinking", "")
    return (content or "").strip()


def _ollama_local(messages: list, max_tokens: int = 8192) -> str:
    model = os.environ.get("OLLAMA_LOCAL_MODEL", OLLAMA_LOCAL_MODEL)
    resp = requests.post(
        OLLAMA_LOCAL_URL,
        json={"model": model, "messages": messages, "stream": False,
              "options": {"num_predict": max_tokens}},
        timeout=300,
    )
    resp.raise_for_status()
    msg = resp.json().get("message", {})
    return (msg.get("content", "") or "").strip()


def _openrouter(messages: list, max_tokens: int = 4096) -> str:
    import time
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY missing in .env")
    for attempt in range(5):
        resp = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json",
                     "HTTP-Referer": "youtube-ai-agent"},
            json={"model": OPENROUTER_MODEL, "messages": messages, "max_tokens": max_tokens},
            timeout=180,
        )
        if resp.status_code == 429:
            wait = 10 * (attempt + 1)
            print(f"[OpenRouter] 429 rate limit — waiting {wait}s (attempt {attempt+1}/5)...", flush=True)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"].get("content")
        if content:
            return content.strip()
        print(f"[OpenRouter] empty response, retry ({attempt+1}/5)...", flush=True)
        time.sleep(10 * (attempt + 1))
    raise RuntimeError("OpenRouter: model unavailable or returning empty content")


def _primary(messages: list, max_tokens: int = 8192) -> str:
    """Call the configured primary AI service."""
    svc = os.environ.get("AI_SERVICE", AI_SERVICE)
    if svc == "openrouter":
        return _openrouter(messages, min(max_tokens, 4096))
    elif svc == "ollama_local":
        return _ollama_local(messages, max_tokens)
    else:  # ollama_cloud (default)
        return _ollama_cloud(messages, max_tokens)


def _fallback(messages: list, max_tokens: int = 4096) -> str:
    """Fallback: if primary is not OpenRouter try it; if primary is OpenRouter try local."""
    svc = os.environ.get("AI_SERVICE", AI_SERVICE)
    if svc == "openrouter":
        # try ollama local as fallback if available
        try:
            return _ollama_local(messages, max_tokens)
        except Exception:
            raise
    else:
        return _openrouter(messages, min(max_tokens, 4096))


# ── public API ────────────────────────────────────────────────────────────────

def chat_ollama(prompt: str, system: str = None, max_tokens: int = 8192) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return _primary(messages, max_tokens)


def chat_openrouter(prompt: str, system: str = None, max_tokens: int = 4096) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return _openrouter(messages, max_tokens)


def chat_with_history(system: str, history: list, user_text: str, max_tokens: int = 2048) -> str:
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    try:
        return _primary(messages, max_tokens)
    except Exception as e:
        print(f"[AI] Primary service failed ({e}), trying fallback...", flush=True)
        return _fallback(messages, max_tokens)
