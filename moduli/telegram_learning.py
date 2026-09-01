"""
Dashboard compatto per Telegram — analytics, learning, strategia, topic memory.
"""

from __future__ import annotations

from typing import Callable

EscFn = Callable[[object], str]


def _esc(value: object, esc: EscFn) -> str:
    return esc(value) if value is not None else ""


def _pattern_label(item) -> str:
    if not item:
        return ""
    if isinstance(item, str):
        return item.strip()
    return (
        item.get("pattern")
        or item.get("value")
        or item.get("label")
        or item.get("pattern_label")
        or ""
    ).strip()


def _video_title(row: dict) -> str:
    return (
        (row.get("title") or (row.get("metrics") or {}).get("title") or "")
        .strip()[:55]
    )


def _best_worst_videos(profiles: list[dict]) -> tuple[dict | None, dict | None]:
    if not profiles:
        return None, None
    try:
        from moduli.performance import score_video
        ranked = sorted(profiles, key=score_video)
        return ranked[-1], ranked[0]
    except Exception:
        return profiles[0], profiles[-1] if len(profiles) > 1 else None


def _video_summary(row: dict | None, esc: EscFn) -> str:
    if not row:
        return "—"
    try:
        from moduli.performance import score_video
        score = round(score_video(row), 1)
    except Exception:
        score = "?"
    title = _video_title(row) or "?"
    tier = row.get("performance_tier") or "?"
    return f"{_esc(title, esc)} ({score}/100, {tier})"


def _strategy_focus(strategy: dict | None, structured: dict | None) -> str:
    st = structured or (strategy or {}).get("structured") or {}
    focus_parts = st.get("topic_focus") or []
    if focus_parts:
        return ", ".join(str(x) for x in focus_parts[:4])
    raw = (strategy or {}).get("topic_focus") or ""
    if raw:
        return str(raw)[:120]
    angle = (strategy or {}).get("preferred_angle") or ""
    if angle:
        return str(angle)[:120]
    return ""


def _next_experiment(strategy: dict | None, structured: dict | None) -> str:
    strategy = strategy or {}
    st = structured or strategy.get("structured") or {}

    exp_block = st.get("experimentation") or {}
    for rec in reversed(exp_block.get("recent") or []):
        if rec.get("status") == "pending" and rec.get("label"):
            return str(rec["label"])[:80]

    try:
        from moduli.experimentation import experiment_stats
        for rec in reversed(experiment_stats().get("recent") or []):
            if rec.get("status") == "pending":
                label = rec.get("label") or rec.get("topic")
                if label:
                    return str(label)[:80]
    except Exception:
        pass

    sub = (strategy.get("_explore_subtheme") or "").strip()
    if sub:
        return sub[:80]

    mode = (strategy.get("_topic_diversity_mode") or "").lower()
    if mode == "explore":
        focus = (strategy.get("topic_focus") or "new topic angle").strip()
        return focus[:80]

    title_exp = strategy.get("_title_experiment") or {}
    if title_exp.get("mode") == "explore":
        return (title_exp.get("pattern_label") or "title structure test")[:80]

    hook_exp = strategy.get("_hook_experiment") or {}
    if hook_exp.get("mode") == "explore":
        return (hook_exp.get("hook_label") or "hook style test")[:80]

    try:
        from moduli.experimentation import experiment_stats
        pool = experiment_stats().get("winning_pool") or []
        if pool:
            return f"iterate: {pool[-1].get('label', '')[:60]}"
    except Exception:
        pass

    return ""


def build_learning_dashboard(
    *,
    state: dict | None = None,
    insights: dict | None = None,
    profiles: list[dict] | None = None,
    strategy: dict | None = None,
    esc: EscFn | None = None,
) -> list[str]:
    """
    Sezioni HTML per Telegram:
    ANALYTICS · LEARNING · NEXT STRATEGY · TOPIC MEMORY
    """
    esc = esc or (lambda v: str(v))
    state = state or {}
    insights = insights or {}
    profiles = profiles or []
    strategy = strategy or state.get("last_strategy") or {}
    structured = strategy.get("structured") or state.get("strategy_structured")

    lines: list[str] = ["🧭 <b>Learning dashboard</b>\n"]

    # --- ANALYTICS ---
    lines.append("📊 <b>ANALYTICS</b>")
    video_count = insights.get("video_count") or len(profiles)
    lines.append(f"Videos analyzed: {video_count}")
    if video_count:
        best, worst = _best_worst_videos(profiles)
        lines.append(f"Best performer: {_video_summary(best, esc)}")
        lines.append(f"Weakest performer: {_video_summary(worst, esc)}")
        avg_ctr = insights.get("avg_ctr")
        avg_ret = insights.get("avg_retention")
        avg_score = insights.get("avg_performance_score")
        metrics_bits = []
        if avg_ctr is not None:
            metrics_bits.append(f"CTR {avg_ctr}%")
        if avg_ret is not None:
            metrics_bits.append(f"ret. {avg_ret}%")
        if avg_score is not None:
            metrics_bits.append(f"score {avg_score}/100")
        if metrics_bits:
            lines.append(f"Channel avg: {_esc(' · '.join(metrics_bits), esc)}")
    else:
        analytics_status = state.get("last_analytics_status")
        if analytics_status:
            lines.append(f"<i>{_esc(analytics_status, esc)}</i>")
        else:
            lines.append("<i>No published videos yet.</i>")

    # --- LEARNING ---
    lines.append("\n🧠 <b>LEARNING</b>")
    winning = insights.get("winning_patterns") or []
    losing = insights.get("losing_patterns") or []
    if not winning and structured:
        winning = structured.get("winning_patterns") or []
    if not losing and structured:
        losing = structured.get("losing_patterns") or []

    win_label = _pattern_label(winning[0]) if winning else ""
    lose_label = _pattern_label(losing[0]) if losing else ""

    if win_label:
        delta = winning[0].get("vs_channel_median") if isinstance(winning[0], dict) else None
        extra = f" (+{delta} pts)" if delta is not None else ""
        lines.append(f"Winning pattern:\n{_esc(win_label, esc)}{_esc(extra, esc)}")
    else:
        lines.append("Winning pattern:\n<i>not enough data yet</i>")

    if lose_label:
        delta = losing[0].get("vs_channel_median") if isinstance(losing[0], dict) else None
        extra = f" ({delta} pts)" if delta is not None else ""
        lines.append(f"Losing pattern:\n{_esc(lose_label, esc)}{_esc(extra, esc)}")
    else:
        lines.append("Losing pattern:\n<i>not enough data yet</i>")

    try:
        from moduli.channel_confidence import confidence_from_profiles
        conf = confidence_from_profiles(profiles)
        lines.append(
            f"Confidence: {_esc(conf.level, esc)} (n={conf.video_count}) — "
            f"<i>{_esc(conf.optimization_mode, esc)}</i>"
        )
    except Exception:
        pass

    # --- NEXT STRATEGY ---
    lines.append("\n🎯 <b>NEXT STRATEGY</b>")
    focus = _strategy_focus(strategy, structured)
    if focus:
        lines.append(f"Focus:\n{_esc(focus, esc)}")
    else:
        lines.append("Focus:\n<i>defaults from preferences</i>")

    experiment = _next_experiment(strategy, structured)
    if experiment:
        lines.append(f"Experiment:\n{_esc(experiment, esc)}")
    else:
        lines.append("Experiment:\n<i>exploit proven formula</i>")

    if structured:
        dur = structured.get("preferred_duration")
        hours = structured.get("best_hours_utc") or []
        if dur:
            lines.append(f"Target length: {dur} min")
        if hours:
            lines.append(f"Best hours UTC: {_esc(str(hours[:4]), esc)}")

    # --- TOPIC MEMORY ---
    lines.append("\n🚫 <b>TOPIC MEMORY</b>")
    try:
        from moduli.topic_history import registry_stats
        stats = registry_stats()
        lines.append(f"Historical topics: {stats.get('historical', 0)}")
        lines.append(f"Duplicate topics rejected: {stats.get('rejected_duplicate', 0)}")
        reserved = stats.get("reserved", 0)
        if reserved:
            lines.append(f"Reserved (queued/manual): {reserved}")
        queue_len = len((state or {}).get("topic_queue") or [])
        if queue_len:
            lines.append(f"Topics in queue: {queue_len}")
    except Exception:
        lines.append("<i>topic registry unavailable</i>")

    return lines


def learning_dashboard_text(**kwargs) -> str:
    return "\n".join(build_learning_dashboard(**kwargs))


def build_analytics_summary(
    *,
    insights: dict | None = None,
    profiles: list[dict] | None = None,
    esc: EscFn | None = None,
) -> list[str]:
    """Riepilogo performance compatto per /analytics."""
    esc = esc or (lambda v: str(v))
    insights = insights or {}
    profiles = profiles or []

    lines: list[str] = ["📊 <b>Analytics summary</b>\n"]
    video_count = insights.get("video_count") or len(profiles)
    lines.append(f"Videos analyzed: {video_count}")

    if not video_count:
        lines.append("<i>No published videos yet.</i>")
        lines.append("\n<i>Full per-video breakdown: /recap</i>")
        return lines

    best, worst = _best_worst_videos(profiles)
    lines.append(f"Best performer: {_video_summary(best, esc)}")
    lines.append(f"Weakest performer: {_video_summary(worst, esc)}")

    metrics_bits = []
    for key, label in (
        ("avg_ctr", "CTR"),
        ("avg_retention", "ret."),
        ("avg_performance_score", "score"),
        ("avg_views", "views"),
    ):
        val = insights.get(key)
        if val is not None:
            suffix = "%" if key in ("avg_ctr", "avg_retention") else ("/100" if key == "avg_performance_score" else "")
            metrics_bits.append(f"{label} {val}{suffix}")
    if metrics_bits:
        lines.append(f"Channel avg: {_esc(' · '.join(str(x) for x in metrics_bits), esc)}")

    by_tier = insights.get("by_tier") or {}
    tier_parts = [
        f"{tier}: {len(by_tier.get(tier) or [])}"
        for tier in ("breakout", "strong", "average", "weak", "poor")
        if by_tier.get(tier)
    ]
    if tier_parts:
        lines.append(f"Classification: {_esc(' · '.join(tier_parts), esc)}")

    for sig in (insights.get("signals") or [])[:3]:
        lines.append(f"• {_esc(sig, esc)}")

    if profiles:
        lines.append("\n<b>Top scores:</b>")
        try:
            from moduli.performance import score_video
            ranked = sorted(profiles, key=score_video, reverse=True)
        except Exception:
            ranked = profiles
        for v in ranked[:5]:
            lines.append(f"• {_video_summary(v, esc)}")

    lines.append("\n<i>Full per-video breakdown: /recap</i>")
    return lines


def build_strategy_summary(
    *,
    state: dict | None = None,
    insights: dict | None = None,
    profiles: list[dict] | None = None,
    strategy: dict | None = None,
    esc: EscFn | None = None,
) -> list[str]:
    """Strategia appresa corrente per /strategy."""
    esc = esc or (lambda v: str(v))
    state = state or {}
    insights = insights or {}
    profiles = profiles or []
    strategy = strategy or state.get("last_strategy") or {}
    structured = strategy.get("structured") or state.get("strategy_structured")

    lines: list[str] = ["🎯 <b>Current learned strategy</b>\n"]

    if not strategy and not structured:
        lines.append("<i>No strategy saved yet — generated on next pipeline run.</i>")
        lines.append("\n<i>Compact dashboard: /learning · Full detail: /strategia</i>")
        return lines

    try:
        from moduli.channel_confidence import confidence_from_profiles
        conf = confidence_from_profiles(profiles)
        lines.append(
            f"Confidence: {_esc(conf.level, esc)} (n={conf.video_count}) — "
            f"<i>{_esc(conf.optimization_mode, esc)}</i>"
        )
    except Exception:
        pass

    focus = _strategy_focus(strategy, structured)
    if focus:
        lines.append(f"\n<b>Focus:</b> {_esc(focus, esc)}")

    for key, label in (
        ("preferred_angle", "Angle"),
        ("content_format", "Format"),
        ("title_style", "Title style"),
        ("hook_strength", "Hook"),
        ("video_style", "Style"),
        ("pacing", "Pacing"),
    ):
        val = strategy.get(key)
        if val:
            lines.append(f"<b>{label}:</b> {_esc(str(val)[:120], esc)}")

    target = strategy.get("target_minutes") or (structured or {}).get("preferred_duration")
    if target:
        lines.append(f"<b>Target length:</b> {target} min")

    winning = insights.get("winning_patterns") or (structured or {}).get("winning_patterns") or []
    losing = insights.get("losing_patterns") or (structured or {}).get("losing_patterns") or []
    if winning:
        wins = "; ".join(_pattern_label(w) for w in winning[:4] if _pattern_label(w))
        if wins:
            lines.append(f"\n<b>Winning patterns:</b> {_esc(wins, esc)}")
    if losing:
        losses = "; ".join(_pattern_label(lp) for lp in losing[:4] if _pattern_label(lp))
        if losses:
            lines.append(f"<b>Losing patterns:</b> {_esc(losses, esc)}")

    avoid = strategy.get("avoid_patterns") or (structured or {}).get("avoid_patterns") or []
    if avoid:
        if isinstance(avoid, str):
            avoid_text = avoid[:200]
        else:
            avoid_text = "; ".join(str(a) for a in avoid[:6])
        lines.append(f"<b>Avoid:</b> {_esc(avoid_text, esc)}")

    experiment = _next_experiment(strategy, structured)
    if experiment:
        lines.append(f"\n<b>Next experiment:</b> {_esc(experiment, esc)}")
    else:
        lines.append("\n<b>Next experiment:</b> <i>exploit proven formula</i>")

    hours = (structured or {}).get("best_hours_utc") or []
    if hours:
        lines.append(f"<b>Best publish hours (UTC):</b> {_esc(str(hours[:6]), esc)}")

    notes = strategy.get("notes") or (structured or {}).get("notes") or ""
    if isinstance(notes, list):
        notes = "; ".join(str(n) for n in notes)
    if notes:
        lines.append(f"\n<b>Notes:</b> {_esc(str(notes)[:400], esc)}")

    lines.append("\n<i>Compact dashboard: /learning · Full detail: /strategia</i>")
    return lines


def build_topics_summary(
    *,
    state: dict | None = None,
    esc: EscFn | None = None,
    max_registry: int = 15,
) -> list[str]:
    """Topic recenti, coda e registro per /topics."""
    esc = esc or (lambda v: str(v))
    state = state or {}
    lines: list[str] = ["📋 <b>Topics</b>\n"]

    queue = state.get("topic_queue") or []
    if queue:
        lines.append("<b>In queue:</b>")
        for i, topic in enumerate(queue, 1):
            lines.append(f"{i}. {_esc(topic, esc)}")
    else:
        lines.append("<b>In queue:</b> <i>empty</i>")

    recent = [t for t in (state.get("recent_topics") or []) if (t or "").strip()]
    if recent:
        lines.append("\n<b>Recently produced:</b>")
        for topic in recent[:12]:
            lines.append(f"• {_esc(topic, esc)}")

    try:
        from moduli.topic_history import load_topic_history
        entries = load_topic_history()
        if entries:
            lines.append("\n<b>Registry (latest):</b>")
            for entry in reversed(entries[-max_registry:]):
                topic = entry.get("topic") or "?"
                status = entry.get("status") or "published"
                date = (entry.get("date") or "")[:10]
                vid = entry.get("video_id")
                extra = f" · {_esc(vid, esc)}" if vid else ""
                lines.append(f"• {_esc(topic, esc)} [{status}] {date}{extra}")
    except Exception:
        lines.append("\n<i>Registry unavailable</i>")

    lines.append("\n<i>Add: /topic &lt;text&gt; · Queue: /coda · Memory: /memory</i>")
    return lines


def build_topic_memory_summary(
    *,
    esc: EscFn | None = None,
    max_entries: int = 20,
) -> list[str]:
    """Registro topic permanente per /memory."""
    esc = esc or (lambda v: str(v))
    lines: list[str] = ["🚫 <b>Topic memory</b>\n"]

    try:
        from moduli.topic_history import (
            STATUS_PUBLISHED,
            STATUS_REJECTED_DUPLICATE,
            STATUS_RESERVED,
            load_topic_history,
            registry_stats,
        )
        stats = registry_stats()
        lines.append(f"Historical topics: {stats.get('historical', 0)}")
        lines.append(f"Published: {stats.get('published', 0)}")
        reserved = stats.get("reserved", 0)
        if reserved:
            lines.append(f"Reserved (manual/queued): {reserved}")
        lines.append(f"Duplicate topics rejected: {stats.get('rejected_duplicate', 0)}")

        entries = load_topic_history()
        if not entries:
            lines.append("\n<i>No topics registered yet.</i>")
            return lines

        by_status: dict[str, list[dict]] = {}
        for entry in entries:
            by_status.setdefault(entry.get("status") or STATUS_PUBLISHED, []).append(entry)

        for status, label in (
            (STATUS_RESERVED, "Reserved"),
            (STATUS_PUBLISHED, "Published"),
            (STATUS_REJECTED_DUPLICATE, "Rejected duplicates"),
        ):
            group = by_status.get(status) or []
            if not group:
                continue
            lines.append(f"\n<b>{label}</b> ({len(group)}):")
            for entry in reversed(group[-max_entries:]):
                topic = entry.get("topic") or "?"
                date = (entry.get("date") or "")[:10]
                row = f"• {_esc(topic, esc)} ({date})"
                if status == STATUS_REJECTED_DUPLICATE:
                    matched = entry.get("matched_topic")
                    if matched:
                        row += f" → dup. of {_esc(matched, esc)}"
                elif entry.get("video_id"):
                    row += f" · {_esc(entry['video_id'], esc)}"
                lines.append(row)
    except Exception as exc:
        lines.append(f"\n<i>Registry unavailable: {_esc(exc, esc)}</i>")

    lines.append(
        "\n<i>Long-term AI notes (separate): /memoria</i>"
    )
    return lines

