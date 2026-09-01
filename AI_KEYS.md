# AI API keys — free fallback setup

Tube Assistant generates topics, scripts, and strategy with LLMs. The **free stack** uses OpenRouter first, then automatically falls back to **Groq** and **Gemini** when rate-limited.

## What to add to your `.env`

Copy from `.env.example`, then fill in these three keys:

```env
OPENROUTER_API_KEY=sk-or-v1-...
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIza...
```

Optional (already have defaults):

```env
AI_SERVICE=openrouter
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free
OPENROUTER_FALLBACK_MODELS=google/gemma-2-9b-it:free,openrouter/free
AI_FALLBACK_SERVICES=groq,gemini,openrouter,ollama_local
GROQ_MODEL=llama-3.3-70b-versatile
GEMINI_MODEL=gemini-2.0-flash
```

After editing `.env`, restart the agent: `python agent.py`

---



## 1. OpenRouter (primary)

1. Go to [https://openrouter.ai/keys](https://openrouter.ai/keys)
2. Sign up / log in
3. Click **Create Key**
4. Copy the key → paste as `OPENROUTER_API_KEY` in `.env`

Free models can hit rate limits during busy hours. That is why Groq + Gemini are configured as backups.

---



## 2. Groq (fallback #1 — fast, free tier)

1. Go to [https://console.groq.com/keys](https://console.groq.com/keys)
2. Sign up with Google or email
3. **API Keys** → **Create API Key**
4. Copy the key (starts with `gsk_`) → `GROQ_API_KEY` in `.env`

Free tier limits apply but are separate from OpenRouter — good safety net for 1 video + Shorts per day.

---



## 3. Google Gemini (fallback #2 — free tier)

1. Go to [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Sign in with Google
3. Click **Create API key**
4. Copy the key (starts with `AIza`) → `GEMINI_API_KEY` in `.env`

---



## How fallback works

```
Request (topic / script / strategy)
    │
    ▼
OpenRouter primary model
    │  (on failure: tries OPENROUTER_FALLBACK_MODELS)
    ▼ still failing?
Groq  →  Gemini  →  OpenRouter again  →  local Ollama (if running)
```

You will see log lines like `[AI] Primary failed ... trying fallback` and `[AI] Trying fallback provider: groq`.

---



## Verify setup

```powershell
cd c:\laragon\www\tube-assistant
uv sync
uv run python -c "from moduli.ai_client import _provider_available; print('openrouter', _provider_available('openrouter')); print('groq', _provider_available('groq')); print('gemini', _provider_available('gemini'))"
```

All three should print `True` after you add keys to `.env`.

---



## Still hitting limits?

- Spread pipeline runs (default: 1 long video/day + 3 Shorts is usually fine)
- Add more models to `OPENROUTER_FALLBACK_MODELS` (browse [openrouter.ai/models](https://openrouter.ai/models) → filter **Free**)
- Install [Ollama](https://ollama.com) locally and keep `ollama_local` in `AI_FALLBACK_SERVICES` as last resort

Never commit `.env` to git — see [SECURITY.md](SECURITY.md).