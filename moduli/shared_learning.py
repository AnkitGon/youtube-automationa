"""Bridge between Shorts and long-form learning signals."""

from __future__ import annotations


def longform_topic_candidates() -> list[dict]:
    """Export strong long-form topics as Short angle candidates."""
    out: list[dict] = []
    try:
        from moduli.performance import carica_profili as load_profiles

        profiles = load_profiles()
        scored = []
        for p in profiles:
            m = p.get("metrics") or {}
            views = int(m.get("views") or 0)
            if views < 50:
                continue
            meta = p.get("content_metadata") or {}
            topic = meta.get("topic") or p.get("title") or ""
            if not topic:
                continue
            scored.append((views, {
                "topic": topic,
                "angle": f"The hidden lesson from {topic[:45]}",
                "hook_hint": f"Nobody talks about this part of {topic.split()[0]}",
                "source_type": "longform_angle",
                "source_topic": topic,
                "source_longform_video_id": p.get("video_id", ""),
                "_score": views,
            }))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = [s[1] for s in scored[:8]]
    except Exception:
        pass
    return out


def shorts_insights_for_longform() -> list[str]:
    """High-confidence Shorts insights for long-form strategy prompts."""
    try:
        from moduli.shorts.strategy import load_strategy

        rollup = (load_strategy().get("rollup") or {})
        lessons = rollup.get("lessons") or []
        hooks = rollup.get("winning_hooks") or []
        insights = []
        for h in hooks[:3]:
            val = h.get("value", h) if isinstance(h, dict) else h
            insights.append(f"Shorts hook pattern working: {val}")
        insights.extend(lessons[:2])
        return insights
    except Exception:
        return []
