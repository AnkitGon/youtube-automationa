
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Autonomous YouTube content pipeline. Daemon (`agent.py`) runs 24/7, triggers per scheduled hour, produces full videos (script → TTS → stock clips → montage → thumbnail → upload) with zero human input. Controlled live via Telegram bot.

## Run / Setup

### First time (new user)
```powershell
.\installa.bat                  # pip install -e . + instructions
youtube-ai-agent onboard        # TUI wizard: AI service → Pexels → Telegram → channel setup via Telegram
youtube-ai-agent start          # start daemon
```
The wizard writes `.env`, `preferenze_video.json`, `memoria_lungo_termine.json`, `credentials.json` to the workspace. No manual file editing needed.

Or without cloning (pip from URL):
```bash
pip install git+https://github.com/user/youtube-ai-agent.git
youtube-ai-agent onboard
youtube-ai-agent start
```

### Already configured
```powershell
python agent.py      # daemon (production)
python main.py       # one-shot pipeline (no scheduler, no Telegram, no checkpoint)
.\avvia_agente.bat   # background via pythonw
```

No test runner configured. `test_*.py` files in root are ad-hoc scripts (`python test_tts.py`), not pytest suites.

Requires: FFmpeg in PATH (MoviePy), `credentials.json` (Google OAuth desktop), `.env` with AI service vars, `PEXELS_API_KEY`, Telegram bot token. All populated by `wizard.py`.

### AI service (`AI_SERVICE` in `.env`)
| Value | Provider | Key var |
|---|---|---|
| `ollama_cloud` | Ollama hosted nemotron-3-super | `OLLAMA_API_KEY` |
| `openrouter` | OpenRouter free/paid | `OPENROUTER_API_KEY` |
| `ollama_local` | Local Ollama instance | `OLLAMA_LOCAL_MODEL` |

`ai_client.py:_primary()` routes to the configured service; `_fallback()` tries a secondary on failure.

## Architecture

Pipeline = 7 stages, each a module in `moduli/`. `agent.py:run_pipeline` orchestrates; `main.py` is a stripped one-shot variant.

| Stage | Module | Role |
|---|---|---|
| Analytics | `analytics.py` | Reads YouTube channel performance via Data API |
| Strategy | `strategia.py` | Maps performance → tone/mood/length hints |
| Brain | `cervello.py` → `ai_client.py` | Topic + JSON script (Ollama Cloud primary, OpenRouter fallback) |
| Audio | `audio.py` | edge-tts → `output/narration.mp3` |
| Clips | `asset.py` | Pexels video search/download → `cache/pexels/` |
| Montage | `montaggio.py` | MoviePy concat + audio sync → `output/output_finale.mp4` |
| Thumbnail | `thumbnail.py` | Pollinations.ai image + Pillow text overlay |
| Publish | `pubblica.py` | YouTube Data API v3 upload + `calcola_publish_slots` for scheduling |

Side channels:
- `moduli/telegram_handler.py` — runs in thread (`start_bot()`). User commands mutate `state.json` (priority tags `[FORZA_ORA]`, `[AGGIUNGI_TOPIC]`, `[PRIORITA_TOPIC]` parsed from LLM replies).
- `moduli/notifiche.py` — push step updates to Telegram.
- `moduli/canale.py` — channel-level metadata helpers.
- `moduli/memoria.py` — long-term notes in `memoria_lungo_termine.json`.

## State & Checkpoints

`state.json` is the single source of truth for the daemon. Hand-edits are valid control surface.

Keys consumed by `agent.py`:
- `videos_per_day` (default 1), `trigger_hours_utc` (default `[14]`), `auto_scheduling` + `best_hours_utc`
- `topic_queue` — FIFO of pending topics
- `recent_topics`, `video_ids` — capped histories
- `force_run` — bypass scheduler once (auto-cleared)
- `abort_pipeline` — raises `PipelineAborted` at next `_check_abort()` (auto-cleared)
- `runs_today` — `{date: count}`, single-day only
- `chat_history` — Telegram per-user message buffer

`output/pipeline_checkpoint.json` records completed steps (`content`, `audio`, `clips`, `montage`, `thumbnail`) for the current day so a crash mid-pipeline resumes instead of restarting. Cleared on success or new day.

`_cleanup_stale_state()` on boot strips `force_run` / `abort_pipeline` and invalid queue entries — anything that should not survive a restart goes there.

## Conventions

- Comments, logs, Telegram replies are Italian. Code identifiers mixed IT/EN — match the surrounding module.
- LLM control protocol: assistant replies in Telegram embed tags like `[FORZA_ORA: x]`, `[AGGIUNGI_TOPIC: x]`, `[RICORDA: x]`, `[AGGIORNA_DESC: x]`, `[AGGIORNA_KEYWORDS: x]`. `telegram_handler.py` parses them and rewrites `state.json` / channel metadata. Preserve this contract when editing prompts.
- `ai_client.py` exposes `_primary()` (routes via `AI_SERVICE` env) and `_fallback()`. Don't bypass — add new providers there following the existing pattern.
- Paths are constants at top of `agent.py` / `main.py` (`AUDIO_PATH`, `VIDEO_PATH`, `THUMB_PATH`). Reuse them.
- `output/` and `cache/` are runtime artifacts. Don't commit. `credentials.json`, `token.json`, `.env` are secrets.
