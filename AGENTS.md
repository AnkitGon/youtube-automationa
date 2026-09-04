# Agent charter — do not break the system

This project runs unattended (daemon + Telegram + YouTube upload).
Any AI agent on any device/IDE (Cursor, Antigravity, Claude Code, etc.) must treat **stability** as the top priority.

This is not about code style. It is about **not breaking working features**.

## Mandatory workflow (every change)

1. **Understand first** — Before editing, read the relevant module(s), their callers, and any related `state.json` / Telegram / env contracts.
2. **Name the blast radius** — State what can break (upload, TTS, Shorts slots, bot commands, scheduling, checkpoints).
3. **Smallest safe change** — Prefer a focused fix over refactors. Do not “clean up” unrelated code.
4. **Preserve contracts** — If you change a parser, prompt tag, env key, JSON shape, or CLI entrypoint, update every consumer in the same change.
5. **Test before return** — When behavior changes, add/update tests under `tests/` and run them successfully before telling the user it is done (Boost-style). Prefer the narrowest relevant suite.
6. **Verify runtime** — Prefer `preflight`, a single module path, or today’s `logs/agent-*.log`. Do not start a second agent process while one is already running.

If the request is unclear or risks the live pipeline, **ask** before changing behavior.

## Sacred contracts (do not break silently)

| Contract | Where | Rule |
|---|---|---|
| Telegram control tags | `moduli/telegram_handler.py` + LLM prompts | Keep tags like `[FORZA_ORA]`, `[AGGIUNGI_TOPIC]`, `[RICORDA]`, `[AGGIORNA_DESC]`, `[AGGIORNA_KEYWORDS]` parseable |
| AI routing | `moduli/ai_client.py` | Add providers via `_primary()` / `_fallback()` — do not bypass |
| Daemon state | `state.json` keys used by `agent.py` | Do not rename/remove keys without migration + all readers updated |
| Pipeline checkpoints | `output/pipeline_checkpoint.json` | Keep step names (`content`, `audio`, `clips`, `montage`, `thumbnail`) compatible |
| Media paths | `agent.py` / `main.py` constants | Reuse `AUDIO_PATH`, `VIDEO_PATH`, `THUMB_PATH` |
| Secrets | `.env`, `credentials.json`, `token.json` | Never commit or paste secrets into git |

Architecture map: see `CLAUDE.md` (pipeline stages and modules).

## Explicitly forbidden without a clear request

- Drive-by refactors, renames, or “modernization” across modules
- Changing scheduler / Shorts slot / publish timing logic “while you’re here”
- Starting a second `agent.py` / bot poller (Telegram `getUpdates` conflict)
- Rewriting working Italian user-facing Telegram strings unless asked (users depend on them)
- Deleting or emptying runtime JSON (`state.json`, learning files) unless asked

## When touching the live pipeline

- Prefer editing offline modules, then one restart of a **single** agent process
- Watch `logs/agent-YYYY-MM-DD.log` for regressions after a change
- Keep long-form and Shorts paths independent unless the task explicitly couples them
