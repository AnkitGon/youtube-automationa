import os
import time
import requests

# ── service routing ───────────────────────────────────────────────────────────
# Set AI_SERVICE in .env:
#   openrouter | ollama_cloud | ollama_local | openai | anthropic | gemini
AI_SERVICE = os.environ.get("AI_SERVICE", "openrouter")

# ── OLLAMA CLOUD ──────────────────────────────────────────────────────────────
OLLAMA_CLOUD_URL   = "https://ollama.com/api/chat"
OLLAMA_CLOUD_MODEL = "nemotron-3-super:cloud"

# ── OLLAMA LOCAL ──────────────────────────────────────────────────────────────
OLLAMA_LOCAL_URL   = "http://localhost:11434/api/chat"
OLLAMA_LOCAL_MODEL = os.environ.get("OLLAMA_LOCAL_MODEL", "llama3.2")

# ── OPENROUTER ────────────────────────────────────────────────────────────────
OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

# ── OPENAI ────────────────────────────────────────────────────────────────────
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# ── ANTHROPIC ─────────────────────────────────────────────────────────────────
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

# ── GEMINI ────────────────────────────────────────────────────────────────────
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


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
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY missing in .env")
    for attempt in range(5):
        resp = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json",
                     "HTTP-Referer": "tube-assistant"},
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


def _openai(messages: list, max_tokens: int = 4096) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing in .env")
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def _anthropic(messages: list, max_tokens: int = 4096) -> str:
    try:
        import anthropic as _anthropic_sdk
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing in .env")
    # extract system message if present
    system = ""
    chat_msgs = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            chat_msgs.append(m)
    client = _anthropic_sdk.Anthropic(api_key=api_key)
    kwargs = {"model": ANTHROPIC_MODEL, "max_tokens": max_tokens, "messages": chat_msgs}
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return resp.content[0].text.strip()


def _gemini(messages: list, max_tokens: int = 4096) -> str:
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai package not installed. Run: pip install google-generativeai")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY missing in .env")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    # convert messages to Gemini format
    history = []
    prompt = ""
    for m in messages:
        if m["role"] == "system":
            history.append({"role": "user", "parts": [m["content"]]})
            history.append({"role": "model", "parts": ["Understood."]})
        elif m["role"] == "user":
            prompt = m["content"]
        elif m["role"] == "assistant":
            history.append({"role": "model", "parts": [m["content"]]})
    chat = model.start_chat(history=history[:-1] if history else [])
    resp = chat.send_message(prompt, generation_config={"max_output_tokens": max_tokens})
    return resp.text.strip()


def _primary(messages: list, max_tokens: int = 8192) -> str:
    svc = os.environ.get("AI_SERVICE", AI_SERVICE)
    if svc == "openrouter":
        return _openrouter(messages, min(max_tokens, 4096))
    elif svc == "ollama_local":
        return _ollama_local(messages, max_tokens)
    elif svc == "openai":
        return _openai(messages, min(max_tokens, 4096))
    elif svc == "anthropic":
        return _anthropic(messages, min(max_tokens, 4096))
    elif svc == "gemini":
        return _gemini(messages, min(max_tokens, 4096))
    else:  # ollama_cloud (default)
        return _ollama_cloud(messages, max_tokens)


def _fallback(messages: list, max_tokens: int = 4096) -> str:
    svc = os.environ.get("AI_SERVICE", AI_SERVICE)
    if svc == "openrouter":
        try:
            return _ollama_local(messages, max_tokens)
        except Exception:
            raise
    else:
        return _openrouter(messages, min(max_tokens, 4096))


# ── public API ────────────────────────────────────────────────────────────────

def chat(prompt: str, system: str = None, max_tokens: int = 8192) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return _primary(messages, max_tokens)


# kept for backwards compatibility
def chat_ollama(prompt: str, system: str = None, max_tokens: int = 8192) -> str:
    return chat(prompt, system, max_tokens)


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
