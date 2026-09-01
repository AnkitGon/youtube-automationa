"""Read-only runtime checks for the local TubeAssistant workspace."""

import importlib.util
import os
import shutil
from pathlib import Path


AI_KEY_BY_SERVICE = {
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
    "ollama_cloud": "OLLAMA_API_KEY",
}


def _has_env(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def run_checks(workspace: str | Path = ".") -> list[dict]:
    ws = Path(workspace)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("workspace", ws.exists(), str(ws.resolve()))
    add(".env", (ws / ".env").exists(), "presente" if (ws / ".env").exists() else "mancante")
    add("credentials.json", (ws / "credentials.json").exists(), "OAuth YouTube")
    add("token.json", (ws / "token.json").exists(), "token esistente" if (ws / "token.json").exists() else "verra creato al primo login")

    try:
        from moduli.ffmpeg_utils import ffmpeg_path
        ffmpeg = ffmpeg_path()
    except FileNotFoundError:
        ffmpeg = None
    add("ffmpeg", bool(ffmpeg), ffmpeg or "non trovato in PATH/FFMPEG_PATH/bundle MoviePy")

    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "PEXELS_API_KEY", "AI_SERVICE"):
        add(key, _has_env(key), "configurato" if _has_env(key) else "mancante")

    service = os.environ.get("AI_SERVICE", "")
    service_key = AI_KEY_BY_SERVICE.get(service)
    if service_key:
        add(service_key, _has_env(service_key), f"chiave per {service}")

    # At least one fallback provider besides primary (rate-limit resilience)
    primary = (service or "openrouter").strip().lower()
    fallbacks_ok = []
    fallbacks_missing = []
    try:
        from moduli.ai_client import _fallback_service_chain, _provider_available
        for fb in _fallback_service_chain():
            if fb == primary:
                continue
            if _provider_available(fb):
                fallbacks_ok.append(fb)
            else:
                fallbacks_missing.append(fb)
    except Exception:
        fallbacks_missing = ["groq", "gemini"]
    add(
        "AI fallbacks",
        len(fallbacks_ok) >= 1,
        f"ready: {', '.join(fallbacks_ok) or 'none'}; "
        f"missing keys: {', '.join(fallbacks_missing) or 'none'}",
    )

    provider = os.environ.get("IMAGE_PROVIDER", "pollinations").lower()
    if provider == "huggingface":
        add("huggingface_hub", importlib.util.find_spec("huggingface_hub") is not None, "richiesto da IMAGE_PROVIDER=huggingface")
        add("HF_API_KEY", _has_env("HF_API_KEY"), "chiave HuggingFace")
    elif provider == "openrouter":
        add("OPENROUTER_API_KEY", _has_env("OPENROUTER_API_KEY"), "thumbnail via OpenRouter")
    else:
        add("image provider", True, provider)

    output = ws / "output"
    cache = ws / "cache"
    add("output dir", output.exists() or os.access(ws, os.W_OK), str(output))
    add("cache dir", cache.exists() or os.access(ws, os.W_OK), str(cache))
    return checks


def format_checks(checks: list[dict]) -> str:
    lines = []
    for check in checks:
        mark = "OK" if check["ok"] else "FAIL"
        detail = f" - {check['detail']}" if check.get("detail") else ""
        lines.append(f"{mark:4} {check['name']}{detail}")
    return "\n".join(lines)
