# Telegram Bot — Command Reference

The agent listens on Telegram while the daemon (`agent.py`) runs. Commands require an authorized chat ID (`TELEGRAM_CHAT_ID` in `.env`).

Italian commands are the originals; English aliases were added for debugging and quick access. **Nothing was removed** — all legacy commands still work.

---

## Quick reference

| Command | Alias | Description |
|---------|-------|-------------|
| `/start` | — | Help and command list |
| `/status` | — | Agent status + learning dashboard |
| `/learning` | — | Compact learning dashboard |
| `/strategy` | `/strategia` | Current learned strategy |
| `/analytics` | `/recap`* | Performance summary |
| `/topics` | `/coda`* | Recent topics, queue, registry |
| `/memory` | — | Topic memory (permanent registry) |
| `/memoria` | — | Long-term AI notes (separate from topic memory) |

\* `/recap` and `/coda` are related but not identical — see sections below.

---

## Pipeline & scheduling

### `/status`
Operational snapshot: pipeline activity, last run, queue size, recent topics, and the learning dashboard.

### `/forza`
Force the pipeline to start within ~60 seconds (normal publish schedule).

### `/forzaora [topic]`
Force immediate pipeline run with **instant publish** (no scheduling). Optional topic is added to the head of the queue (validated against topic memory).

```
/forzaora Why Nokia failed in smartphones
```

### `/skip`
Mark today's video quota as complete — skips remaining runs for the day.

### `/abort`
Request pipeline abort at the next safe checkpoint. Montage may finish before stopping.

### `/setvideogiorno <1-5>`
How many videos to produce per day.

```
/setvideogiorno 2
```

### `/setpubblica <ora1> [ora2] ...`
Set publish hours in **UTC**. Production runs ~3 hours before each publish slot.

```
/setpubblica 14 20
```

### `/autoscheduling on|off`
Enable/disable automatic publish-hour optimization from analytics.

```
/autoscheduling on
```

### `/orari`
Show current production and publish schedule.

### `/prossimi`
Next pipeline trigger and next scheduled publish time.

---

## Strategy & learning

### `/learning`
Compact dashboard with four sections:

- **ANALYTICS** — videos analyzed, best/weakest performer, channel averages
- **LEARNING** — winning/losing patterns, confidence level
- **NEXT STRATEGY** — focus, experiment, target length, best hours
- **TOPIC MEMORY** — historical topics, rejected duplicates, queue

### `/strategy` (alias EN)
Current **learned strategy** from the last pipeline run: focus, formats, winning/losing patterns, avoid list, next experiment, publish hours.

Italian equivalent with full detail: `/strategia`.

### `/strategia`
Full strategy report: learning dashboard + detailed breakdown (title/hook/thumbnail learning, experiments, strategy memory, history).

### `/analytics` (alias EN)
Performance summary: averages, tier classification, top scores, key signals.

For per-video metrics (views, CTR, retention line-by-line): `/recap`.

`/recap` forces a live YouTube API refresh. Other commands (`/status`, `/learning`, `/analytics`, `/strategy`, `/strategia`) use cached data when fresh (default TTL 90 minutes, env `ANALYTICS_CACHE_TTL_MINUTES`).

### `/recap`
Fetches live YouTube analytics and lists the last videos with full metrics (score, tier, views, impressions, CTR, retention).

---

## Topics & memory

### `/topics` (alias EN)
Overview of all topic sources:

1. **In queue** — pending manual/auto topics
2. **Recently produced** — last topics from `state.json`
3. **Registry** — latest entries from `topic_history.json`

### `/coda`
Queue only (numbered list for `/deltopic`).

### `/topic <text>`
Add a topic to the end of the queue. Validated immediately and registered in topic memory as `reserved`.

```
/topic The rise and fall of Blockbuster
```

### `/deltopic <number>`
Remove topic by position (use `/coda` or `/topics` for numbers).

```
/deltopic 2
```

### `/memory` (alias EN)
**Topic memory** — permanent registry (`topic_history.json`):

- Published topics (never repeated semantically)
- Reserved topics (manual/queued, blocked before publish)
- Rejected duplicates (AI topics blocked as too similar)

### `/memoria`
**Long-term AI memory** — free-form notes the bot remembers across chats (`memoria_lungo_termine.json`). *Not* the same as `/memory`.

### `/dimentica <n>` | `/dimentica tutto`
Remove a long-term memory entry by number, or clear all.

```
/dimentica 3
/dimentica tutto
```

---

## Channel management

### `/canale`
Channel info and statistics.

### `/setdesc <text>`
Update channel description via YouTube API.

### `/video`
List recent uploaded videos.

### `/playlist`
List channel playlists.

### `/nuovaplaylist <name>`
Create a new playlist.

### `/commenti <videoId>`
Read comments on a video.

```
/commenti dQw4w9WgXcQ
```

---

## Preferences

### `/preferenze`
Show current video preferences (`preferenze_video.json`).

### `/setpref <key> <value>`
Update a preference key.

```
/setpref durata_target_minuti 8
/setpref tts_voce en-US-GuyNeural
```

Common keys: `ritmo`, `tono_voce`, `lingua`, `stile_clip`, `stile_thumbnail`, `durata_target_minuti`, `tts_voce`, `argomenti_preferiti`, `argomenti_evitare`.

---

## Safety & confirmation

Destructive or irreversible actions from the AI chat are queued for explicit confirmation.

### `/conferma <id>`
Confirm a pending action (shown in the bot reply).

### `/annulla <id>`
Cancel a pending action.

### `/reset`
Reset agent state (see bot reply for scope).

---

## Natural language (no slash)

You can also chat freely. The AI can:

- Add topics: `[AGGIUNGI_TOPIC: …]`, `[PRIORITA_TOPIC: …]`
- Force pipeline: `[FORZA_ORA: …]` (requires `/conferma`)
- Save memories: `[RICORDA: …]`
- Update preferences: `[SETPREF: key=value]`
- Generate standalone assets: thumbnail, audio, script

See `moduli/telegram_handler.py` → `SYSTEM_PROMPT` for the full tag protocol.

---

## Debugging tips

| Goal | Command |
|------|---------|
| Is the agent alive? | `/status` |
| What will it do next? | `/strategy` or `/learning` |
| Why was a topic rejected? | `/memory` |
| Is analytics working? | `/analytics` then `/recap` |
| What's queued? | `/topics` or `/coda` |
| Full strategy dump | `/strategia` |

---

## Files touched by commands

| File | Used by |
|------|---------|
| `state.json` | Queue, scheduling, last strategy |
| `topic_history.json` | `/memory`, `/topics` |
| `memoria_lungo_termine.json` | `/memoria` |
| `preferenze_video.json` | `/preferenze`, `/setpref` |
| `video_performance_profiles.json` | `/analytics`, `/recap`, `/strategia` |
| `strategy_memory.json` | `/strategia` (long-term learning) |
