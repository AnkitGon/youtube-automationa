# Security & sharing this project

This repository is safe to clone and share **as long as you never commit private files**.

## Never commit

| File / folder | Why |
|---------------|-----|
| `.env` | API keys, bot token, chat ID |
| `credentials.json` | Google OAuth client secret |
| `token.json` | YouTube OAuth access/refresh tokens |
| `state.json` | Daemon state, may include chat history |
| `preferenze_video.json` | Your channel style preferences |
| `channel_learning.json`, `strategy_memory.json`, `video_performance_profiles.json`, etc. | **Your channel analytics & learning data** |
| `shorts_state.json`, `shorts_profiles.json`, `shorts_history.json`, `shorts_strategy.json` | Shorts runtime + performance |
| `topic_history.json` | Your published topics |
| `output/`, `cache/`, `logs/` | Generated videos and API caches |

All of the above are listed in `.gitignore`.

## What teammates need to run it

1. Clone this repo
2. Copy `.env.example` → `.env` and fill in **their own** keys:
   - AI provider (`OPENROUTER_API_KEY` or other)
   - `PEXELS_API_KEY`
   - `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
3. Run the setup wizard (`tube-assistant onboard` or `python wizard.py`)
4. Provide **their own** Google Cloud `credentials.json` for YouTube upload
5. Start the daemon (`python agent.py` or `tube-assistant start`)

Each person gets a **fresh** learning state — no shared analytics, topics, or OAuth tokens.

## Before you push

```bash
git status
```

Confirm you do **not** see `.env`, `credentials.json`, `token.json`, `state.json`, or any `*_profiles.json` / `channel_learning.json` in staged files.

If a secret was ever committed, rotate that key immediately and use `git filter-repo` or GitHub secret scanning — do not rely on a normal delete commit alone.

## Optional: pre-push check

```bash
git diff --cached --name-only | findstr /i ".env credentials token state.json channel_learning"
```

(No output = good on Windows.)
