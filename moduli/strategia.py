import json
import os
import re
from datetime import datetime, timezone
from moduli.ai_client import chat_ollama
from moduli.preferenze import carica as carica_preferenze

HISTORY_FILE = "strategia_storia.json"

DEFAULT_STRATEGY = {
    "topic_focus": "AI and technology trends",
    "title_style": "curiosity-driven, slightly provocative",
    "tone": "confident and informative",
    "hook_strength": "medium",
    "notes": "No prior data. Use standard approach.",
}

STRATEGY_PROMPT = """You are a long-term YouTube growth strategist for a tech/AI channel.

Recent video performance:
{performance_json}

Previous strategies tried (most recent first):
{history_json}

User preferences (HARD CONSTRAINTS — never violate):
{preferences}

Produce an EVOLVED strategy that:
- Learns from what's working and what isn't (use CTR, retention, views)
- Avoids repeating failed approaches from history
- Doubles down on patterns that increased CTR or retention
- Respects user preferences absolutely

Reply ONLY valid JSON:
{{
  "topic_focus": "what topics/angles to pursue next",
  "title_style": "concrete title writing style",
  "tone": "narration tone",
  "hook_strength": "soft | medium | aggressive",
  "notes": "specific lessons learned from past performance + improvement plan for next video"
}}

Rules:
- If avg CTR < 3%: bolder, more curiosity-driven titles
- If retention < 40%: shorter sentences, harder hook, more pacing variety
- If views < 100 on multiple videos: experiment with NEW topic angles, not just title tweaks
- If a strategy from history shows improvement: keep that direction
- Reply ONLY with JSON, no explanation.
"""


def _load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_history(history: list) -> None:
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-20:], f, indent=2, ensure_ascii=False)


def calcola_strategia(performance: list[dict]) -> dict:
    pref = carica_preferenze()
    if not performance:
        return {**DEFAULT_STRATEGY, "topic_focus": ", ".join(pref.get("argomenti_preferiti", []))}
    history = _load_history()
    try:
        prompt = STRATEGY_PROMPT.format(
            performance_json=json.dumps(performance, indent=2),
            history_json=json.dumps(history[-5:], indent=2) if history else "[]",
            preferences=json.dumps(pref, indent=2, ensure_ascii=False),
        )
        text = chat_ollama(prompt, max_tokens=600)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            strategy = json.loads(match.group())
            # salva nella storia per evoluzione futura
            history.append({
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "strategy": strategy,
                "perf_snapshot": [
                    {"title": v.get("title", "")[:50],
                     "views": v.get("views", 0),
                     "ctr": v.get("ctr_percent", 0),
                     "retention_pct": int(v.get("avg_view_duration_seconds", 0) /
                                          max(v.get("duration_seconds", 1), 1) * 100)}
                    for v in performance[:5]
                ],
            })
            _save_history(history)
            return strategy
    except Exception as e:
        print(f"Strategy generation failed: {e}. Using default.")
    return DEFAULT_STRATEGY


def storia_strategia() -> list:
    return _load_history()
