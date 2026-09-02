# AI API keys — setup

Tube Assistant generates topics, scripts, and strategy with LLMs. **OpenRouter** is the primary service; on rate limits it retries alternate free models via `OPENROUTER_FALLBACK_MODELS`.

## What to add to your `.env`

```env
OPENROUTER_API_KEY=sk-or-v1-...
AI_SERVICE=openrouter
OPENROUTER_MODEL=minimax/minimax-m3:free
OPENROUTER_USE_FREE_MODEL_POOL=1
OPENROUTER_ROTATE_ON_429=1
OPENROUTER_FALLBACK_RETRY_WAIT_SEC=30
AI_FALLBACK_SERVICES=openrouter
```

After editing `.env`, restart the agent: `python agent.py`

---

## OpenRouter (primary)

1. Go to [https://openrouter.ai/keys](https://openrouter.ai/keys)
2. Sign up / log in
3. Click **Create Key**
4. Copy the key → paste as `OPENROUTER_API_KEY` in `.env`

Free models can hit rate limits during busy hours. The client waits and retries, then tries `OPENROUTER_FALLBACK_MODELS`.

---

## How fallback works

```
Request (topic / script / strategy)
    │
    ▼
OpenRouter primary model
    │  (on failure: waits, retries, tries OPENROUTER_FALLBACK_MODELS)
    ▼ still failing?
OpenRouter again via AI_FALLBACK_SERVICES (same provider, second pass)
```

Optional: set `AI_FALLBACK_SERVICES=openrouter,ollama_local` if you run [Ollama](https://ollama.com) locally.

---

## Verify setup

```powershell
cd c:\laragon\www\tube-assistant
uv sync
uv run python -c "from moduli.ai_client import _provider_available; print('openrouter', _provider_available('openrouter'))"
```

Never commit `.env` to git — see [SECURITY.md](SECURITY.md).
