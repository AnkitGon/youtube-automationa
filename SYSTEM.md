# Tube Assistant — System Reference

End-to-end guide for the autonomous YouTube production engine: how it works, how learning adapts over time, scheduling, Shorts, configuration, and what stays private when you share the repo.

> **Telegram bot commands** are documented in [TELEGRAM.md](TELEGRAM.md).  
> **Secrets & safe sharing** are documented in [SECURITY.md](SECURITY.md).

---

## Table of contents

1. [What this system is](#1-what-this-system-is)
2. [How to run it](#2-how-to-run-it)
3. [Architecture overview](#3-architecture-overview)
4. [Daemon loop vs publish timing](#4-daemon-loop-vs-publish-timing)
5. [The production pipeline](#5-the-production-pipeline)
6. [Checkpoints and crash recovery](#6-checkpoints-and-crash-recovery)
7. [Control surface & runtime state](#7-control-surface--runtime-state)
8. [Strategy & learning](#8-strategy--learning)
9. [Topic selection & deduplication](#9-topic-selection--deduplication)
10. [Research & trending](#10-research--trending)
11. [Content quality & narration](#11-content-quality--narration)
12. [Media production](#12-media-production)
13. [Publish scheduling](#13-publish-scheduling)
14. [YouTube upload & captions](#14-youtube-upload--captions)
15. [YouTube Shorts](#15-youtube-shorts)
16. [Analytics & performance](#16-analytics--performance)
17. [Confidence & fallbacks](#17-confidence--fallbacks)
18. [AI providers](#18-ai-providers)
19. [Configuration](#19-configuration)
20. [What is stored locally](#20-what-is-stored-locally)
21. [Capabilities & limitations](#21-capabilities--limitations)

---

## 1. What this system is

Tube Assistant is a **24/7 autonomous YouTube production daemon** that:

- Reads **your** channel analytics and builds a data-driven content strategy
- Selects **non-repeating** topics (semantic dedup, not just string matching)
- Generates scripts, narration, stock montage, thumbnails, and subtitles
- Uploads to YouTube with an **explicit scheduled publish timestamp**
- **Learns cumulatively** from CTR, retention, watch time, subscribers, traffic sources, audience timing, and scheduling outcomes

### Design principles

| Principle | What it means |
|-----------|----------------|
| **Audience time, not PC time** | YouTube receives a UTC publish timestamp; audience timezone comes from config + geography |
| **Code decides schedule** | AI suggests strategy; publish time is computed deterministically from analytics + config |
| **Never repeat the same story** | Permanent topic registry + semantic similarity |
| **Reuse categories, not subjects** | Another “company failure” documentary is fine; the same company/story arc is not |
| **Compact learning** | Analytics are summarized into channel-relative signals before any AI prompt — raw API dumps are never sent to the model |
| **Confidence-gated** | Small channels keep conservative defaults until multiple videos support a pattern |
| **Fail safe** | Analytics, AI, and scheduling degrade gracefully; the daemon should not crash on missing data |

---

## 2. How to run it

### First time (new machine / teammate)

1. Clone the repository
2. Copy `.env.example` → `.env` and fill in your keys (AI, Pexels, Telegram)
3. Run the **setup wizard** — it configures OAuth, channel preferences, and initial state
4. Ensure **FFmpeg** is installed and on your PATH
5. Start the **daemon** for 24/7 operation, or run a **one-shot** pipeline for a single video

### Already configured

- **Daemon (production):** runs on a schedule, checkpoints, Telegram control, full learning stack
- **One-shot:** single video end-to-end, no scheduler, immediate upload option

### Requirements

- Python 3.11+
- FFmpeg
- Google account with YouTube Data API + Analytics API (OAuth desktop flow)
- Telegram bot (optional but recommended for control)
- AI API key (OpenRouter free tier works)
- Pexels API key (free)

See [SECURITY.md](SECURITY.md) — teammates each use **their own** `.env`, OAuth files, and learning data.

---

## 3. Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Daemon (60s tick)                         │
│   Should run? → Full pipeline → Notifications → Learning     │
└─────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
   Runtime state                  Pipeline modules
   (local JSON)                   Analytics → Strategy → Content
                                  → Audio → Clips → Edit
                                  → Thumbnail → Upload
         │                              │
         └──────────────┬───────────────┘
                        ▼
              YouTube / AI / Pexels / TTS
```

**Orchestrator:** the main agent process runs the seven-stage pipeline when the schedule (or a manual trigger) fires.

**Side channels:**

- **Telegram bot** — live commands, topic queue, force run, status
- **Notifications** — step updates pushed to your chat
- **Shorts engine** — separate daily Shorts slots, isolated failure handling

---

## 4. Daemon loop vs publish timing

These are **two different clocks**:

| Concept | Meaning |
|---------|---------|
| **Pipeline trigger** | When the agent **produces** a video (script → render → upload) |
| **Publish time** | When **YouTube makes the video public** (`publishAt` on upload) |

Example:

```
14:00 UTC  →  pipeline starts (produce video)
…hours of render/upload…
Next day   →  YouTube publishAt (e.g. 18:00 in audience timezone)

Your PC can be off after upload — YouTube handles publication.
```

### Trigger hours

Resolved in priority order:

1. Explicit trigger hours in runtime state (manual override)
2. Legacy manual publish hours (when auto-scheduling is off)
3. Default from environment (e.g. 14 UTC)

Capped by videos-per-day setting (max 5).

### Publish time

**Never** taken from the local PC clock or invented by the AI.

1. Infer audience timezone from geography (countries / US regions) or configured default
2. Load **when viewers are on YouTube** from Analytics when available (day-of-week + hour grid)
3. Apply confidence rules → pick peak window or fallback schedule
4. Convert to UTC (DST-aware) and validate future timestamp
5. Send RFC3339 UTC string to YouTube on upload

Every decision is logged with confidence, timezone, peak day/hour, fallback flag, and reason.

---

## 5. The production pipeline

### Stage 1 — Analytics & strategy

1. Fetch recent video performance (cached when fresh)
2. Fetch audience activity, geography, and optional channel reports (traffic, demographics, subscriber watch split, monthly trend)
3. Cache scheduling data for the upload step (one fetch per cycle)
4. Build **deterministic insights** (CTR, retention, patterns, confidence)
5. Build **compact learning summary** (channel baselines, per-video diagnoses, audience lines, action signals)
6. LLM strategy JSON using trimmed insights + learning text — **not** raw analytics
7. Update cumulative learning files and publish-timing hints in state
8. Log learning stage (cold start → established channel)

### Stage 2 — Topic & script

- Topic from queue or AI generation with strategy, trending, diversity, and **analytics learning** context
- Gates: topic quality → avoid patterns → semantic duplicate check (retries with category pivot)
- Script with research brief, strategy guidance, analytics feedback, content quality gate
- Checkpoint saves topic + content JSON

### Stage 3 — Audio

- Edge TTS primary (voice from preferences), gTTS fallback
- Optional pause compression for natural flow between sentences

### Stage 4 — Clips

- Pexels search/download per script keywords
- Local cache for reuse

### Stage 5 — Montage

- FFmpeg (or MoviePy fallback) — concat clips, sync narration, optional music & burned key captions

### Stage 6 — Thumbnail

- AI background (Pollinations / HuggingFace / fallbacks) + text overlay

### Stage 7 — Publish

- Pre-publish quality gate (unless explicitly skipped)
- Deterministic schedule decision → upload as private + `publishAt` or immediate public
- Captions upload when enabled
- Register outcome for learning loop

---

## 6. Checkpoints and crash recovery

A daily checkpoint records completed steps (content, audio, clips, montage, thumbnail).

- **Crash mid-pipeline:** resume from last completed step same day
- **New day:** checkpoint cleared, fresh run
- **Success:** checkpoint cleared

Stale control flags (`force_run`, `abort`, immediate publish) are cleaned on daemon boot.

---

## 7. Control surface & runtime state

**Runtime state** (local, not in git) holds:

| Area | Examples |
|------|----------|
| Scheduling | videos per day, auto-scheduling, trigger hours, best publish hours |
| Queue | pending topics, recent topics, video IDs |
| Control | force run once, abort pipeline, publish immediately |
| Counters | runs today |
| Cache | last audience activity + geography fetch |
| Telegram | per-user chat buffer |

**User preferences** (local): voice, language, pacing, niche topics, thumbnail style, target duration.

Hand-editing state is supported for power users; Telegram commands are the normal control surface.

---

## 8. Strategy & learning

### Strategy computation

1. Deterministic performance analysis (channel-relative)
2. Compact learning enrichment (baselines, diagnoses, audience summary)
3. LLM produces strategy JSON (topic focus, tone, hooks, pacing, duration, avoid patterns, notes)
4. On LLM failure → analytics-only fallback
5. On total failure → standard strategy from user preferences
6. Structured strategy attached for dashboards and downstream prompts

**Strategy fields** include topic focus, angle, format, title style, tone, hook strength, script structure, target minutes, pacing, video/thumbnail style, avoid patterns, and notes.

### Compact analytics learning

Raw YouTube data is **never** pasted into AI prompts. Instead:

| Output | Purpose |
|--------|---------|
| Channel baselines | Median CTR, retention, views/day, watch minutes, sub rate — **vs your channel only** |
| Per-video cards | Strength labels: strong / average / weak / insufficient data |
| Diagnoses | e.g. high CTR + low retention → packaging may overpromise |
| Action signals | Conservative messaging when n≤2 videos; trend-based when n grows |
| Audience summary | Peak activity, traffic sources, demographics, geo, sub vs non-sub watch time, monthly trend — only when API returns data |

**Packaging vs satisfaction loop:**

- High CTR + weak retention → soften titles/thumbnails/hooks; deliver value earlier
- Weak CTR + strong retention → improve packaging without dumbing content down
- Strong views + weak subs → deepen differentiation and subscribe-worthy payoff

Learning is **cumulative** — updated after each analytics cycle, not overwritten by the latest video alone.

### Cumulative memory layers

| Layer | Holds |
|-------|--------|
| Strategy memory | Historical winning/losing patterns with evidence |
| Channel learning | Publish timing, scheduling history, clickbait traps, retention lessons, content quality lessons, audience insights |
| Performance profiles | Per-video metrics + content metadata at publish time |
| Topic history | Permanent registry of covered subjects |
| Shorts strategy | Hook/angle/publish patterns for vertical content |

### Learning stages by video count

| Videos | Behavior |
|--------|----------|
| 0 | Preferences only; cold start |
| 1 | Baseline collected |
| 2 | Early learning — weak signals; dedup always on |
| 3–5 | Growing sample — cautious pattern claims |
| 6–9 | Maturing — stronger optimization + experiments |
| 10–49 | Established — exploit winners + controlled explore |
| 50+ | Deep channel-specific memory |

### Content prompt injection

Topic and script generation both receive an **analytics learning** section: baselines, diagnoses, Shorts cross-insights, learning stage, clickbait traps, quality lessons, and the category-vs-subject reuse rule.

---

## 9. Topic selection & deduplication

### Generation flow

1. **Exploit vs explore** — default ~75% proven direction, ~25% experimentation
2. Prompt with strategy, memory, avoid patterns, trending, diversity levers, analytics learning
3. LLM returns a short concrete topic phrase
4. Quality gate → avoid patterns → semantic duplicate check
5. Retries with category pivot if duplicate

### Permanent registry

Every accepted/published topic is stored with normalized form, entities, category, and identity hash.

**Blocks** rewordings of the same story (e.g. “How Nokia lost the war” vs “Why Nokia failed in smartphones”).

**Allows** same **category** with a **different subject** (Nokia vs BlackBerry vs Kodak).

### Trending balance

Trending feeds influence **topic discovery only**, not publish time. Balance:

- Proven channel topics
- Emerging/trending tech stories
- Audience interests from analytics
- Experimental angles

Never chase trends blindly; deliver evergreen informational value.

---

## 10. Research & trending

Before scripting, a **research brief** gathers web snippets for the topic (when search is available).

Topics are labeled by origin: manual, queue, trending, exploit, explore, or analytics-driven.

---

## 11. Content quality & narration

### In-generation checks

- AI filler phrase detection
- Viewer value / insight density
- Title + thumbnail complement (not duplicate words)
- Visual plan specificity (reject generic stock keywords)
- Combined quality gate with retries

### Human-sounding narration

Scripts are written for **spoken TTS delivery**:

- Natural sentence flow — not staccato dramatic beats
- Varied length; conversational transitions
- No formulaic “But here’s the thing…”, fake curiosity, or robotic pacing
- Analytics and retention feedback adjust pacing when channel evidence supports it
- Information density preserved — no artificial pauses for drama

### Pre-upload gate

Blocks upload on: duplicate topic, quality failures, missing files, empty captions (when required), excessive filler.

Warnings (non-fatal): long title, known clickbait trap pattern.

---

## 12. Media production

| Step | Technology |
|------|------------|
| Voice | Edge TTS → gTTS fallback; optional pause compression |
| Clips | Pexels API, local cache |
| Edit | FFmpeg montage, synced audio, optional music |
| Captions | SRT generation + optional burn-in of key phrases |
| Thumbnail | AI image + Pillow text overlay |

Low-power mode available for ARM / Raspberry Pi (lighter encode settings).

---

## 13. Publish scheduling

### Schedule decision

Each upload gets a structured decision: UTC timestamp, audience timezone, local label, peak day/hour, confidence, whether fallback was used, source (analytics / manual / fallback), and human-readable reason.

### Viewer activity signal

**Primary:** Analytics day-of-week + hour grid when the API returns it (closest to Studio’s “when your viewers are on YouTube”).

**Fallback:** weekday rollup from daily views + configured default hour or historical publish-hour performance when ≥2 videos support the same hour.

The AI **never** chooses publish time.

### Confidence (scheduling)

| Channel size | Typical behavior |
|--------------|------------------|
| 0–2 videos | Fallback schedule |
| 3–5 | Cautious analytics if activity signal is strong |
| 6+ | Analytics preferred when data exists |

Stability rules prevent wild hour jumps between uploads on medium confidence.

### Strategy-layer publish optimization

Separate from the final timestamp: ranks publish hours/days by your videos’ composite performance. Updates **hints** in state (`best_hours_utc`) only when confidence allows — never a single-video overreaction.

---

## 14. YouTube upload & captions

- **Scheduled:** upload private + `publishAt` (RFC3339 UTC)
- **Immediate:** public now (control flag or one-shot mode)
- Thumbnail attached after video insert
- Captions uploaded when SRT exists and scope allows
- Default category: Science & Technology

---

## 15. YouTube Shorts

Separate pipeline from long-form — up to **3 Shorts per day**, one per production window (morning / afternoon / evening in audience local time).

| Aspect | Behavior |
|--------|----------|
| Trigger | One Short per window; catch-up if daemon was offline |
| Structure | Hook → context → escalation → payoff → optional CTA |
| Dedup | Fingerprint history; related long-form angles allowed, lazy summaries blocked |
| Duration | Configurable min/max seconds (default 20–60) |
| Render | 9:16 vertical, burned ASS captions |
| Upload | Same YouTube API; publish lead minutes after render |
| Learning | Separate profiles + strategy rollup; high-confidence insights can inform long-form |
| Failures | Isolated per slot — one failure does not block others |

Copy `shorts_strategy.example.json` → `shorts_strategy.json` on first run if missing (wizard may create empty state).

Telegram Shorts commands: see [TELEGRAM.md](TELEGRAM.md).

---

## 16. Analytics & performance

### Per-video metrics (when API allows)

Views, likes, comments, average view duration, average view percentage, watch time, impressions, CTR, shares, subscribers gained/lost, retention at 30s, geography.

Missing metrics are skipped cleanly — never invented.

### Channel-level reports (optional, one fetch per cycle)

| Report | Used for |
|--------|----------|
| Hour grid | When viewers are on YouTube |
| Traffic sources | How viewers find the channel |
| Demographics | Age/gender segments |
| Subscriber watch split | Watch time from subs vs non-subs |
| Monthly audience | Views/watch time trend by month |
| Geography | Top countries (+ US regions for timezone) |

### Performance profiles

Each published video gets a persistent profile: metrics, composite score, tier, content metadata (title pattern, hook type, etc.), and strategy snapshot at publish.

Patterns detected across profiles feed winning/losing buckets by title, hook, format, duration, publish hour, and topic category.

### Cache

Analytics snapshots cached with TTL to reduce API quota; stale profiles used when live fetch fails.

---

## 17. Confidence & fallbacks

### Channel confidence

| Videos | Learning applied | Publish schedule changes |
|--------|------------------|--------------------------|
| 0–2 | Minimal | No |
| 3–5 | Yes | Conservative |
| 6–9 | Yes | Yes |
| 10+ | Yes | Yes (stronger evidence required) |

### Master fallback ladder

```
Topic:     retries → error if exhausted
Content:   retries → error if exhausted
Strategy:  LLM → analytics signals → default preferences
AI:        primary provider → secondary → local
Analytics: cache → profiles → API → empty (safe defaults)
Schedule:  analytics → configured default time + timezone
Upload:    quality gate blocks unless explicitly skipped
TTS:       Edge → gTTS → error
Thumbnail: AI providers → clip frame → gradient
```

---

## 18. AI providers

Set primary service in `.env` (`AI_SERVICE`). Supported providers include OpenRouter, OpenAI, Anthropic, Gemini, Mistral, Groq, DeepSeek, xAI, Cohere, Together, Perplexity, Fireworks, Azure OpenAI, Ollama Cloud, and local Ollama.

Automatic fallback chain on failure. JSON mode for structured outputs (strategy, content). See `.env.example` for all keys and models.

---

## 19. Configuration

### Environment (`.env`)

Copy from `.env.example`. Key groups:

| Group | Examples |
|-------|----------|
| AI | service, API keys, models |
| Media | Pexels, thumbnail provider, FFmpeg path |
| Telegram | bot token, chat ID |
| Publish | default time, audience timezone, trigger hours, scheduler thresholds |
| Shorts | enabled, per day, production hours, timezone, duration limits |
| TTS | pause compression thresholds |
| Quality | skip gates (testing only) |

### User preferences (local file, created by wizard)

Pacing, voice, language, clip style, thumbnail style, preferred/avoided topics, target duration.

### Runtime state (local)

Scheduling mode, queues, caches — see §7.

---

## 20. What is stored locally

### Safe in git (code, docs, examples)

Source code, tests, `.env.example`, `shorts_strategy.example.json`, documentation.

### Never in git (per-user / per-channel)

See [SECURITY.md](SECURITY.md) for the full list. Summary:

- Secrets: `.env`, OAuth credentials, tokens
- Runtime: state, preferences, checkpoints
- Learning: analytics profiles, strategy memory, topic history, channel learning, Shorts state/history/profiles/strategy

Teammates start fresh; only shared code and `.env.example` travel through git.

---

## 21. Capabilities & limitations

### Can do

- End-to-end video production without daily manual work
- Schedule at audience-local times via YouTube `publishAt`
- Learn from analytics to improve topics, packaging, hooks, scripts, pacing, and timing
- Block semantic topic duplicates
- Resume after crashes
- Run on modest hardware (Pi-safe encoding)
- Multiple AI providers with fallback
- Quality gates before upload
- Long-form + Shorts in parallel

### Limitations

| Area | Note |
|------|------|
| Hour grid | Used when API returns it; some channels lack sufficient data |
| Shorts CTR/impressions | Often unavailable from Analytics API |
| Stock footage | Pexels only; relevance depends on keywords |
| Voice | TTS, not cloned human voice |
| Thumbnails | AI quality varies by provider availability |
| Free AI tiers | Rate limits — configure fallbacks |
| OAuth | Caption upload may require re-auth if scopes changed |
| YouTube quota | Upload quota resets Pacific midnight |
| Income | Automation ≠ monetization; YPP eligibility is separate |

### Operational checklist

1. Install dependencies (`uv sync` or pip install)
2. Configure `.env` from example
3. Run setup wizard (OAuth + Telegram + preferences)
4. FFmpeg on PATH
5. Start daemon; monitor logs and Telegram notifications

---

*For bot commands see [TELEGRAM.md](TELEGRAM.md). For sharing safely see [SECURITY.md](SECURITY.md).*

uv run python agent.py