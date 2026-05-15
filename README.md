# TubeAssistant

> **Run a YouTube channel on autopilot — no editing, no scripting, no scheduling.**

---

## The Problem

Growing a YouTube channel is a second job. Every single day you need to:

- Research what topics are working
- Write a full script
- Record or synthesize a voice-over
- Find and edit video footage
- Design a thumbnail
- Write SEO-optimized titles, descriptions, and tags
- Upload and schedule at the right time
- Analyze performance to improve the next video

**Most creators quit within 3 months** — not because they lack ideas, but because the process is relentless and eats hours every day.

TubeAssistant eliminates every step of that process. It runs 24/7, reads your channel analytics, generates content, and publishes — completely autonomously.

---

## How It Works

```
Analytics → Strategy → AI Script → TTS Voice → Stock Clips → Montage → AI Thumbnail → Upload
```

Every day, at the time you choose, TubeAssistant:

1. **Reads your channel analytics** to understand what's performing
2. **Picks a topic** aligned with your niche and goals
3. **Writes a full script** using an LLM (OpenRouter, Ollama Cloud, or local)
4. **Synthesizes narration** with Edge TTS — natural voice, zero cost
5. **Downloads stock footage** from Pexels (free library, millions of clips)
6. **Edits the video** with FFmpeg — synced audio, background music
7. **Generates a thumbnail** with AI (Pollinations.ai / Flux) + text overlay
8. **Uploads to YouTube** and schedules at the optimal time

Everything controllable in real time via **Telegram** — just message your bot.

---

## Requirements

- Python 3.11+
- FFmpeg in PATH ([download](https://ffmpeg.org/download.html))
- A Google account with YouTube Data API enabled
- A Telegram bot (free, 2 minutes via @BotFather)
- An AI service API key (OpenRouter has a free tier)
- A Pexels API key (free)

---

## Installation

### 1. Clone

```bash
git clone https://github.com/your-username/tube-assistant.git
cd tube-assistant
```

### 2. Install

```bash
pip install .
```

On Windows:

```bat
installa.bat
```

### 3. Guided setup

```bash
youtube-ai-agent onboard
```

The TUI wizard walks you through everything:

```
Step 1 — AI Service      OpenRouter / Ollama Cloud / local Ollama
Step 2 — Pexels API      Free key for stock footage
Step 3 — Telegram Bot    Token from @BotFather
Step 4 — Channel setup   The agent asks via Telegram:
                           • Channel name and niche
                           • Content goals
                           • Video style and language
                           • Thumbnail aesthetic
                           → Send your Google credentials.json
```

No manual file editing. Everything saved automatically.

### 4. Start

```bash
youtube-ai-agent start
```

Background mode:

```bat
# Windows
avvia_agente.bat

# Linux / macOS
./start.sh
```

---

## Telegram Control

Once running, message your bot to control TubeAssistant live:

| Command | Action |
|---|---|
| `/status` | Current agent state |
| `/forza` | Trigger pipeline immediately |
| `/forzaora <topic>` | Publish now with a specific topic |
| `/topic <text>` | Add topic to queue |
| `/coda` | View topic queue |
| `/skip` | Skip today's video |
| `/setpubblica <hour>` | Change publish time (UTC) |
| `/setvideogiorno <n>` | Videos per day (1–5) |
| `/canale` | Channel info and stats |
| `/recap` | Analytics on recent videos |
| `/memoria` | What the agent remembers |

You can also write freely — the bot understands natural language:

> *"Next video about the future of remote work"*
> *"Avoid mentioning crypto"*
> *"Make the pacing faster"*

---

## AI Services

| Service | Cost | Config |
|---|---|---|
| **OpenRouter** | Free tier available | `AI_SERVICE=openrouter` + `OPENROUTER_API_KEY` |
| **Ollama Cloud** | Paid | `AI_SERVICE=ollama_cloud` + `OLLAMA_API_KEY` |
| **Local Ollama** | Free (your hardware) | `AI_SERVICE=ollama_local` + `OLLAMA_LOCAL_MODEL` |

---

## CLI

```bash
youtube-ai-agent onboard    # First-time setup wizard
youtube-ai-agent start      # Start the 24/7 daemon
youtube-ai-agent run        # One-shot pipeline (no scheduler)
youtube-ai-agent status     # Show workspace and config
youtube-ai-agent workspace  # Print workspace path
```

---

## Workspace

All runtime files live in `~/.youtube-ai-agent/`:

```
~/.youtube-ai-agent/
  .env                        # API keys and config
  credentials.json            # Google OAuth (sent via Telegram)
  state.json                  # Daemon state
  preferenze_video.json       # Style, language, topics
  memoria_lungo_termine.json  # Agent long-term memory
  output/                     # Produced videos, audio, thumbnails
  cache/pexels/               # Downloaded clips (reused)
  assets/music/               # Background music tracks
  logs/                       # Daemon logs
```

Custom workspace:

```bash
YOUTUBE_AI_WORKSPACE=/custom/path youtube-ai-agent start
```

---

## Architecture

```
youtube_ai_agent/       CLI and launcher (pip entry point)
moduli/
  cervello.py           Topic and script generation (LLM)
  audio.py              Voice synthesis (Edge TTS)
  asset.py              Pexels clip download
  montaggio.py          Video editing (FFmpeg / MoviePy)
  thumbnail.py          AI thumbnail generation (Pollinations.ai + Pillow)
  pubblica.py           YouTube Data API v3 upload
  analytics.py          Channel performance reading
  strategia.py          Strategy adaptation from analytics
  telegram_handler.py   Telegram bot (live control)
  ai_client.py          Multi-provider AI client
agent.py                Main daemon (24/7 scheduler)
setup.py                Configuration wizard
```

---

## Cost

| Service | Cost |
|---|---|
| OpenRouter free tier | $0 |
| Pexels API | $0 |
| Telegram bot | $0 |
| Pollinations.ai (thumbnails) | $0 |
| Edge TTS (voice) | $0 |
| YouTube Data API | $0 (standard quota) |

**Total: $0/month** on free tiers.

---

## License

MIT — use, modify, and distribute freely.
