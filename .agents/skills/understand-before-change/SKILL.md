---
name: understand-before-change
description: >-
  Use before editing agent.py, moduli/*, Telegram, scheduling, Shorts, upload,
  or state.json. Forces read-and-trace of existing behavior so changes do not
  break the live YouTube pipeline.
---

# Understand before change

Use this whenever the task touches the daemon, pipeline, Telegram bot, AI client, Shorts, publish, or shared JSON state.

## Steps

1. **Locate** the entrypoint for the feature (often `agent.py`, `main.py`, or `moduli/<area>.py`).
2. **Read** the current implementation end-to-end for that path — not just the one function named in the request.
3. **Trace contracts**:
   - Telegram tags / handlers if bot-related
   - `state.json` keys if scheduling/queue/control-related
   - `ai_client._primary` / `_fallback` if model/provider-related
   - checkpoint step names if resume/crash-recovery-related
4. **Summarize** in one short paragraph: current behavior + what will change + what must stay identical.
5. **Edit minimally**. Do not refactor neighbors.
6. **Write or update tests** for the behavior you changed (add cases in `tests/` next to existing coverage).
7. **Run those tests** and fix failures before answering the user. Do not return “done” on red tests.
8. **Sanity-check**: grep for old symbol names / tags you changed; ensure every consumer was updated.
9. **Runtime caution**: only one `agent.py` should poll Telegram; prefer checking `logs/agent-YYYY-MM-DD.log` after risky changes.

If you cannot explain current behavior from the code, stop and ask the user — do not guess.
