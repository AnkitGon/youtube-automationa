# Do not break this system (Always On)

Priority is **working features**, not coding style.
Any agent editing this repo on any machine must follow this.

## Before every change
1. Read the target module and its callers/callees first.
2. Follow the charter in @AGENTS.md (Telegram tags, AI routing, state.json, checkpoints).
3. Prefer the smallest safe diff. No drive-by refactors.
4. If behavior is unclear or risky for the live daemon, ask before changing it.

## Never
- Bypass `ai_client` `_primary()` / `_fallback()`
- Break Telegram control-tag parsing in `telegram_handler.py`
- Rename or drop `state.json` / checkpoint keys without updating all consumers
- Run a second `agent.py` while one is already polling Telegram
- Commit or paste secrets (`.env`, `credentials.json`, `token.json`)

Architecture context: @CLAUDE.md
