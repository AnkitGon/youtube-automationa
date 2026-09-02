import os
import time
import random
import threading
import requests

# ── sampling context ──────────────────────────────────────────────────────────
# Senza temperature/seed il modello tende a rigenerare sempre lo stesso testo
# (titolo e contenuto identici). Ogni chiamata riceve un seed casuale e una
# temperatura alta così l'output varia. Thread-safe: il bot Telegram gira in
# un thread separato e non deve condividere il seed con la pipeline.
_sampling_ctx = threading.local()


def _set_sampling(temperature=None, seed=None) -> None:
    _sampling_ctx.temperature = temperature
    _sampling_ctx.seed = seed


def _temp(default: float = 0.9) -> float:
    t = getattr(_sampling_ctx, "temperature", None)
    return default if t is None else t


def _seed() -> int:
    s = getattr(_sampling_ctx, "seed", None)
    return s if s is not None else random.randint(1, 2_147_483_647)

# ── service routing ───────────────────────────────────────────────────────────
# Set AI_SERVICE in .env — supported values:
#   openrouter | openai | anthropic | gemini | mistral | groq | deepseek
#   xai | cohere | together | perplexity | fireworks | azure_openai
#   ollama_cloud | ollama_local
AI_SERVICE = os.environ.get("AI_SERVICE", "openrouter")

# ── model defaults (all overridable via env) ──────────────────────────────────
OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openrouter/free")

OPENAI_MODEL     = os.environ.get("OPENAI_MODEL",     "gpt-4o-mini")
ANTHROPIC_MODEL  = os.environ.get("ANTHROPIC_MODEL",  "claude-3-5-haiku-20241022")
GEMINI_MODEL     = os.environ.get("GEMINI_MODEL",     "gemini-2.5-flash")
MISTRAL_MODEL    = os.environ.get("MISTRAL_MODEL",    "mistral-small-latest")
GROQ_MODEL       = os.environ.get("GROQ_MODEL",       "llama-3.1-8b-instant")
DEEPSEEK_MODEL   = os.environ.get("DEEPSEEK_MODEL",   "deepseek-chat")
XAI_MODEL        = os.environ.get("XAI_MODEL",        "grok-2-1212")
COHERE_MODEL     = os.environ.get("COHERE_MODEL",     "command-r-plus-08-2024")
TOGETHER_MODEL   = os.environ.get("TOGETHER_MODEL",   "meta-llama/Llama-3.3-70B-Instruct-Turbo")
PERPLEXITY_MODEL = os.environ.get("PERPLEXITY_MODEL", "llama-3.1-sonar-large-128k-online")
FIREWORKS_MODEL  = os.environ.get("FIREWORKS_MODEL",  "accounts/fireworks/models/llama-v3p3-70b-instruct")
AZURE_OPENAI_MODEL      = os.environ.get("AZURE_OPENAI_MODEL",      "gpt-4o-mini")
AZURE_OPENAI_ENDPOINT   = os.environ.get("AZURE_OPENAI_ENDPOINT",   "")
AZURE_OPENAI_API_VERSION= os.environ.get("AZURE_OPENAI_API_VERSION","2024-08-01-preview")

OLLAMA_CLOUD_URL   = "https://ollama.com/api/chat"
OLLAMA_CLOUD_MODEL = "nemotron-3-super:cloud"
OLLAMA_LOCAL_URL   = "http://localhost:11434/api/chat"
OLLAMA_LOCAL_MODEL = os.environ.get("OLLAMA_LOCAL_MODEL", "llama3.2")

# Provider con limite token più alto (script lunghi, JSON strutturato)
_HIGH_CAP_SERVICES = frozenset({"ollama_cloud", "ollama_local", "openrouter"})

_OPENROUTER_MAX_ATTEMPTS = max(1, int(os.environ.get("OPENROUTER_MAX_ATTEMPTS", "4")))

# Text-capable free models on OpenRouter (auto-rotated when one 429s/404s).
# Override/extend via OPENROUTER_FALLBACK_MODELS; set OPENROUTER_USE_FREE_MODEL_POOL=0 to disable pool.
_OPENROUTER_FREE_MODEL_POOL = [
    "openrouter/free",
    "minimax/minimax-m3:free",
    "minimax/minimax-m2.7:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "z-ai/glm-5.2:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "poolside/laguna-s-2.1:free",
    "poolside/laguna-xs-2.1:free",
    "liquid/lfm-2.5-2.6b:free",
    "inclusionai/ling-3.0-flash-fin:free",
    "cohere/north-mini-code:free",
    "dots-studio/dots-3-note-preview:free",
]

_DEPRECATED_GEMINI_MODELS = {
    "gemini-2.0-flash": "gemini-2.5-flash",
    "models/gemini-2.0-flash": "gemini-2.5-flash",
}


def _normalize_gemini_model(model: str) -> str:
    m = (model or "").strip()
    return _DEPRECATED_GEMINI_MODELS.get(m, m)


def _groq_model_chain() -> list[str]:
    primary = (os.environ.get("GROQ_MODEL") or GROQ_MODEL or "").strip()
    raw = os.environ.get(
        "GROQ_FALLBACK_MODELS",
        "llama-3.1-8b-instant,llama-3.3-70b-versatile",
    )
    chain: list[str] = []
    for model in [primary, *[m.strip() for m in raw.split(",") if m.strip()]]:
        if model and model not in chain:
            chain.append(model)
    return chain or ["llama-3.1-8b-instant"]


def _gemini_model_chain() -> list[str]:
    primary = _normalize_gemini_model(os.environ.get("GEMINI_MODEL") or GEMINI_MODEL)
    raw = os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash,gemini-2.0-flash-lite")
    chain: list[str] = []
    for model in [primary, *[m.strip() for m in raw.split(",") if m.strip()]]:
        model = _normalize_gemini_model(model)
        if model and model not in chain:
            chain.append(model)
    return chain or ["gemini-2.5-flash"]


def _ollama_local_reachable() -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.4):
            return True
    except OSError:
        return False


# ── helpers ───────────────────────────────────────────────────────────────────

def _openrouter_model_chain() -> list[str]:
    """Primary + env fallbacks + full free pool (deduped)."""
    primary = (os.environ.get("OPENROUTER_MODEL") or OPENROUTER_MODEL or "").strip()
    raw_fallbacks = os.environ.get("OPENROUTER_FALLBACK_MODELS", "")
    fallbacks = [m.strip() for m in raw_fallbacks.split(",") if m.strip()]
    use_pool = os.environ.get("OPENROUTER_USE_FREE_MODEL_POOL", "1").lower() not in {
        "0", "false", "no",
    }
    chain: list[str] = []
    for model in [primary, *fallbacks, *(_OPENROUTER_FREE_MODEL_POOL if use_pool else [])]:
        if model and model not in chain:
            chain.append(model)
    max_models = int(os.environ.get("OPENROUTER_MAX_MODELS_IN_CHAIN", "0") or "0")
    if max_models > 0:
        chain = chain[:max_models]
    return chain or ["openrouter/free"]


def _openrouter_reasoning_payload(model: str) -> dict:
    """Only nemotron-lightning needs reasoning disabled; others break with effort:none."""
    if "nemotron-3.5-lightning" in model:
        return {"reasoning": {"effort": "none"}}
    return {}


def _fallback_service_chain() -> list[str]:
    """Provider order when primary fails (env AI_FALLBACK_SERVICES, comma-separated)."""
    default = "openrouter"
    raw = os.environ.get("AI_FALLBACK_SERVICES", default)
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def _provider_available(svc: str) -> bool:
    """True if we can attempt this provider (key present or local/no-key service)."""
    if svc == "ollama_local":
        return _ollama_local_reachable()
    if svc == "ollama_cloud":
        return bool(os.environ.get("OLLAMA_API_KEY", "").strip())
    key_name = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "groq": "GROQ_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "xai": "XAI_API_KEY",
        "cohere": "COHERE_API_KEY",
        "together": "TOGETHER_API_KEY",
        "perplexity": "PERPLEXITY_API_KEY",
        "fireworks": "FIREWORKS_API_KEY",
        "azure_openai": "AZURE_OPENAI_API_KEY",
    }.get(svc)
    if not key_name:
        return False
    return bool(os.environ.get(key_name, "").strip())


def _message_content_text(message: dict) -> str | None:
    """Estrae solo message.content — mai reasoning/thinking."""
    raw = message.get("content")
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        return text or None
    if isinstance(raw, list):
        parts = []
        for part in raw:
            if isinstance(part, dict):
                if part.get("type") in ("text", "output_text") and part.get("text"):
                    parts.append(part["text"])
                elif part.get("text"):
                    parts.append(part["text"])
        text = "".join(parts).strip()
        return text or None
    return None


def _openai_compat(messages: list, max_tokens: int, base_url: str, api_key: str,
                   model: str, referer: str = "tube-assistant",
                   json_mode: bool = False) -> str:
    """Generic OpenAI-compatible endpoint (OpenAI, DeepSeek, xAI, Together, Perplexity, Fireworks)."""
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")
    client = OpenAI(api_key=api_key, base_url=base_url)
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": _temp(),
        "seed": _seed(),
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content
    if not content or not str(content).strip():
        finish = getattr(resp.choices[0], "finish_reason", None)
        raise RuntimeError(f"OpenAI-compat ({model}): empty content (finish_reason={finish})")
    return str(content).strip()


# ── providers ─────────────────────────────────────────────────────────────────

def _openrouter(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY missing in .env")

    models = _openrouter_model_chain()
    last_err: str | None = None
    rotate_on_429 = os.environ.get("OPENROUTER_ROTATE_ON_429", "1").lower() not in {
        "0", "false", "no",
    }

    for model in models:
        payload: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": _temp(),
            "seed": _seed(),
            ** _openrouter_reasoning_payload(model),
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(_OPENROUTER_MAX_ATTEMPTS):
            resp = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "tube-assistant",
                },
                json=payload,
                timeout=180,
            )
            status = resp.status_code
            print(
                f"[OpenRouter] model={model} status={status} attempt={attempt + 1}/{_OPENROUTER_MAX_ATTEMPTS}",
                flush=True,
            )

            if status == 429:
                last_err = "429 rate limit"
                if rotate_on_429:
                    print(f"[OpenRouter] 429 on {model} — rotating to next free model", flush=True)
                    break
                base = max(10, int(os.environ.get("OPENROUTER_RATE_LIMIT_WAIT_SEC", "15")))
                wait = base * (attempt + 1)
                print(f"[OpenRouter] 429 rate limit — waiting {wait}s...", flush=True)
                time.sleep(wait)
                continue
            if status in (400, 404, 403):
                try:
                    err_body = resp.json().get("error", {}).get("message", resp.text[:120])
                except Exception:
                    err_body = resp.text[:120]
                last_err = f"HTTP {status}: {err_body}"
                print(f"[OpenRouter] {model} unavailable ({status}) — next model", flush=True)
                break
            if status >= 500:
                wait = 5 * (attempt + 1)
                print(f"[OpenRouter] {status} provider error — waiting {wait}s...", flush=True)
                time.sleep(wait)
                last_err = f"HTTP {status}"
                continue

            try:
                resp.raise_for_status()
            except requests.HTTPError as e:
                last_err = str(e)
                break

            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            finish_reason = choice.get("finish_reason")
            print(f"[OpenRouter] finish_reason={finish_reason}", flush=True)

            content = _message_content_text(message)
            if content:
                return content

            # Mai usare reasoning come risposta — solo diagnostica
            has_reasoning = bool(message.get("reasoning") or message.get("reasoning_details"))
            if has_reasoning and not content:
                print(
                    "[OpenRouter] content vuoto ma reasoning presente — "
                    "probabilmente budget token esaurito dal reasoning",
                    flush=True,
                )
                if finish_reason == "length" and not json_mode:
                    payload["max_tokens"] = max(max_tokens, max_tokens * 2)
                    if "nemotron-3.5-lightning" in model:
                        payload["reasoning"] = {"effort": "none"}
                last_err = f"empty content (finish_reason={finish_reason})"
                if attempt + 1 < _OPENROUTER_MAX_ATTEMPTS:
                    time.sleep(5 * (attempt + 1))
                continue

            last_err = f"empty content (finish_reason={finish_reason})"
            if attempt + 1 < _OPENROUTER_MAX_ATTEMPTS:
                time.sleep(5 * (attempt + 1))

        print(f"[OpenRouter] model {model} failed: {last_err}", flush=True)

    raise RuntimeError(f"OpenRouter: all models failed — last error: {last_err}")


def _openai(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing in .env")
    return _openai_compat(
        messages, max_tokens, "https://api.openai.com/v1", api_key, OPENAI_MODEL,
        json_mode=json_mode,
    )


def _anthropic(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    try:
        import anthropic as sdk
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing in .env")
    system = ""
    chat_msgs = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            chat_msgs.append(m)
    client = sdk.Anthropic(api_key=api_key)
    kwargs = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": chat_msgs,
        "temperature": _temp(),
    }
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return resp.content[0].text.strip()


def _gemini(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai not installed. Run: pip install google-generativeai")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY missing in .env")
    genai.configure(api_key=api_key)

    history, prompt = [], ""
    for m in messages:
        if m["role"] == "system":
            history += [{"role": "user", "parts": [m["content"]]},
                        {"role": "model", "parts": ["Understood."]}]
        elif m["role"] == "user":
            prompt = m["content"]
        elif m["role"] == "assistant":
            history.append({"role": "model", "parts": [m["content"]]})

    gen_cfg = {"max_output_tokens": max_tokens, "temperature": _temp()}
    if json_mode:
        gen_cfg["response_mime_type"] = "application/json"

    last_err: Exception | None = None
    for model_name in _gemini_model_chain():
        try:
            model = genai.GenerativeModel(model_name)
            chat = model.start_chat(history=history)
            resp = chat.send_message(prompt, generation_config=gen_cfg)
            text = (resp.text or "").strip()
            if text:
                if model_name != _normalize_gemini_model(os.environ.get("GEMINI_MODEL") or GEMINI_MODEL):
                    print(f"[Gemini] using fallback model: {model_name}", flush=True)
                return text
            last_err = RuntimeError(f"Gemini ({model_name}): empty response")
        except Exception as e:
            err = str(e).lower()
            last_err = e
            if "404" in err or "not found" in err or "no longer available" in err:
                print(f"[Gemini] model {model_name} unavailable — trying next", flush=True)
                continue
            raise
    raise RuntimeError(f"Gemini: all models failed — last error: {last_err}")


def _mistral(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    try:
        from mistralai import Mistral
    except ImportError:
        raise RuntimeError("mistralai not installed. Run: pip install mistralai")
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY missing in .env")
    client = Mistral(api_key=api_key)
    kwargs = {
        "model": MISTRAL_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": _temp(),
        "random_seed": _seed(),
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.complete(**kwargs)
    return resp.choices[0].message.content.strip()


def _groq(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    try:
        from groq import Groq
    except ImportError:
        raise RuntimeError("groq not installed. Run: pip install groq")
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY missing in .env")
    client = Groq(api_key=api_key)

    last_err: Exception | None = None
    for model_name in _groq_model_chain():
        kwargs = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": _temp(),
            "seed": _seed(),
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = client.chat.completions.create(**kwargs)
            content = (resp.choices[0].message.content or "").strip()
            if content:
                if model_name != (os.environ.get("GROQ_MODEL") or GROQ_MODEL):
                    print(f"[Groq] using fallback model: {model_name}", flush=True)
                return content
            last_err = RuntimeError(f"Groq ({model_name}): empty content")
        except Exception as e:
            err = str(e).lower()
            last_err = e
            if "404" in err or "model_not_found" in err or "does not exist" in err:
                print(f"[Groq] model {model_name} unavailable — trying next", flush=True)
                continue
            if "429" in err or "rate limit" in err:
                wait = 8 * (1 + list(_groq_model_chain()).index(model_name))
                print(f"[Groq] rate limit on {model_name} — waiting {wait}s...", flush=True)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Groq: all models failed — last error: {last_err}")


def _deepseek(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY missing in .env")
    return _openai_compat(
        messages, max_tokens, "https://api.deepseek.com/v1", api_key, DEEPSEEK_MODEL,
        json_mode=json_mode,
    )


def _xai(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("XAI_API_KEY missing in .env")
    return _openai_compat(
        messages, max_tokens, "https://api.x.ai/v1", api_key, XAI_MODEL,
        json_mode=json_mode,
    )


def _cohere(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    try:
        import cohere
    except ImportError:
        raise RuntimeError("cohere not installed. Run: pip install cohere")
    api_key = os.environ.get("COHERE_API_KEY", "")
    if not api_key:
        raise RuntimeError("COHERE_API_KEY missing in .env")
    client = cohere.ClientV2(api_key=api_key)
    resp = client.chat(model=COHERE_MODEL, messages=messages, max_tokens=max_tokens,
                       temperature=_temp(), seed=_seed())
    return resp.message.content[0].text.strip()


def _together(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    api_key = os.environ.get("TOGETHER_API_KEY", "")
    if not api_key:
        raise RuntimeError("TOGETHER_API_KEY missing in .env")
    return _openai_compat(
        messages, max_tokens, "https://api.together.xyz/v1", api_key, TOGETHER_MODEL,
        json_mode=json_mode,
    )


def _perplexity(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        raise RuntimeError("PERPLEXITY_API_KEY missing in .env")
    return _openai_compat(
        messages, max_tokens, "https://api.perplexity.ai", api_key, PERPLEXITY_MODEL,
        json_mode=json_mode,
    )


def _fireworks(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    api_key = os.environ.get("FIREWORKS_API_KEY", "")
    if not api_key:
        raise RuntimeError("FIREWORKS_API_KEY missing in .env")
    return _openai_compat(
        messages, max_tokens, "https://api.fireworks.ai/inference/v1", api_key, FIREWORKS_MODEL,
        json_mode=json_mode,
    )


def _azure_openai(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    try:
        from openai import AzureOpenAI
    except ImportError:
        raise RuntimeError("openai not installed. Run: pip install openai")
    api_key  = os.environ.get("AZURE_OPENAI_API_KEY", "")
    endpoint = AZURE_OPENAI_ENDPOINT
    if not api_key or not endpoint:
        raise RuntimeError("AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT required in .env")
    client = AzureOpenAI(api_key=api_key, azure_endpoint=endpoint,
                         api_version=AZURE_OPENAI_API_VERSION)
    kwargs = {
        "model": AZURE_OPENAI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": _temp(),
        "seed": _seed(),
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content.strip()


def _ollama_cloud(messages: list, max_tokens: int = 8192, json_mode: bool = False) -> str:
    api_key = os.environ.get("OLLAMA_API_KEY", "")
    body: dict = {
        "model": OLLAMA_CLOUD_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"num_predict": max_tokens, "temperature": _temp(), "seed": _seed()},
    }
    if json_mode:
        body["format"] = "json"
    resp = requests.post(
        OLLAMA_CLOUD_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=300,
    )
    resp.raise_for_status()
    msg = resp.json().get("message", {})
    # content only — mai thinking come risposta
    return (msg.get("content", "") or "").strip()


def _ollama_local(messages: list, max_tokens: int = 8192, json_mode: bool = False) -> str:
    model = os.environ.get("OLLAMA_LOCAL_MODEL", OLLAMA_LOCAL_MODEL)
    body: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": _temp(), "seed": _seed()},
    }
    if json_mode:
        body["format"] = "json"
    resp = requests.post(OLLAMA_LOCAL_URL, json=body, timeout=300)
    resp.raise_for_status()
    return (resp.json().get("message", {}).get("content", "") or "").strip()


# ── dispatch table ────────────────────────────────────────────────────────────

_PROVIDERS = {
    "openrouter":   _openrouter,
    "openai":       _openai,
    "anthropic":    _anthropic,
    "gemini":       _gemini,
    "mistral":      _mistral,
    "groq":         _groq,
    "deepseek":     _deepseek,
    "xai":          _xai,
    "cohere":       _cohere,
    "together":     _together,
    "perplexity":   _perplexity,
    "fireworks":    _fireworks,
    "azure_openai": _azure_openai,
    "ollama_cloud": _ollama_cloud,
    "ollama_local": _ollama_local,
}


def _token_cap(svc: str, max_tokens: int) -> int:
    if svc in _HIGH_CAP_SERVICES:
        return max_tokens
    return min(max_tokens, 4096)


def _primary(messages: list, max_tokens: int = 8192, json_mode: bool = False) -> str:
    svc = os.environ.get("AI_SERVICE", AI_SERVICE)
    fn = _PROVIDERS.get(svc)
    if fn is None:
        raise RuntimeError(f"Unknown AI_SERVICE '{svc}'. Valid: {', '.join(_PROVIDERS)}")
    return fn(messages, _token_cap(svc, max_tokens), json_mode=json_mode)


def _fallback(messages: list, max_tokens: int = 4096, json_mode: bool = False) -> str:
    """Try backup providers when primary fails (rate limit, outage, empty response)."""
    primary_svc = os.environ.get("AI_SERVICE", AI_SERVICE).strip().lower()
    last_err: Exception | None = None

    for name in _fallback_service_chain():
        if name == primary_svc:
            # Primary is OpenRouter and chain is openrouter-only → wait and retry model chain
            if name == "openrouter" and _provider_available("openrouter"):
                wait = max(15, int(os.environ.get("OPENROUTER_FALLBACK_RETRY_WAIT_SEC", "30")))
                print(f"[AI] Retrying OpenRouter model chain after {wait}s...", flush=True)
                time.sleep(wait)
                try:
                    cap = _token_cap(name, max_tokens)
                    return _openrouter(messages, cap, json_mode=json_mode)
                except Exception as e:
                    print(f"[AI] OpenRouter retry failed: {e}", flush=True)
                    last_err = e
            continue
        if name not in _PROVIDERS:
            print(f"[AI] Fallback skip unknown service: {name}", flush=True)
            continue
        if not _provider_available(name):
            reason = "not running" if name == "ollama_local" else "no API key / not configured"
            print(f"[AI] Fallback skip {name} ({reason})", flush=True)
            continue
        fn = globals().get(f"_{name}")
        if not callable(fn):
            print(f"[AI] Fallback skip {name} (provider not loaded)", flush=True)
            continue
        try:
            print(f"[AI] Trying fallback provider: {name}", flush=True)
            cap = _token_cap(name, max_tokens)
            return fn(messages, cap, json_mode=json_mode)
        except Exception as e:
            print(f"[AI] Fallback {name} failed: {e}", flush=True)
            last_err = e

    raise RuntimeError(f"All AI fallback providers failed: {last_err}")


# ── public API ────────────────────────────────────────────────────────────────

def chat(prompt: str, system: str = None, max_tokens: int = 8192,
         json_mode: bool = False) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        return _primary(messages, max_tokens, json_mode=json_mode)
    except Exception as e:
        # provider primario giù non deve far perdere il video del giorno
        print(f"[AI] Primary failed ({e}), trying fallback...", flush=True)
        return _fallback(messages, max_tokens, json_mode=json_mode)


def chat_ollama(prompt: str, system: str = None, max_tokens: int = 8192,
                json_mode: bool = False) -> str:
    return chat(prompt, system, max_tokens, json_mode=json_mode)


def chat_openrouter(prompt: str, system: str = None, max_tokens: int = 4096,
                    json_mode: bool = False) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return _openrouter(messages, max_tokens, json_mode=json_mode)


def chat_with_history(system: str, history: list, user_text: str, max_tokens: int = 2048,
                      json_mode: bool = False) -> str:
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    try:
        return _primary(messages, max_tokens, json_mode=json_mode)
    except Exception as e:
        print(f"[AI] Primary failed ({e}), trying fallback...", flush=True)
        return _fallback(messages, max_tokens, json_mode=json_mode)
