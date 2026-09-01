"""Post-publish Shorts learning rollup."""

from __future__ import annotations

import statistics
from collections import defaultdict

from moduli.shorts.profiles import load_profiles
from moduli.shorts.strategy import load_strategy, save_strategy, default_strategy


def run_learning_update() -> dict:
    profiles = [p for p in load_profiles() if (p.get("metrics") or {}).get("views", 0) > 0]
    data = load_strategy()
    data["cycles"] = int(data.get("cycles", 0)) + 1
    rollup = data.get("rollup") or default_strategy()["rollup"]

    if len(profiles) < 2:
        save_strategy(data)
        return data

    scored = []
    for p in profiles:
        m = p.get("metrics") or {}
        views = int(m.get("views") or 0)
        pct = float(m.get("pct_viewed") or m.get("avg_view_percentage") or 0)
        score = views * 0.4 + pct * 0.6
        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    median = statistics.median(s[0] for s in scored) if scored else 0

    hook_buckets: dict[str, list[float]] = defaultdict(list)
    angle_buckets: dict[str, list[float]] = defaultdict(list)
    hour_buckets: dict[int, list[float]] = defaultdict(list)

    for score, p in scored:
        meta = p.get("content_metadata") or {}
        hook = meta.get("hook_type") or meta.get("hook", "")[:40]
        angle = meta.get("angle") or ""
        if hook:
            hook_buckets[hook].append(score)
        if angle:
            angle_buckets[angle].append(score)
        pub = p.get("published_at") or ""
        try:
            from datetime import datetime
            h = datetime.fromisoformat(pub.replace("Z", "+00:00")).hour
            hour_buckets[h].append(score)
        except Exception:
            pass

    def _top(buckets: dict, n: int = 5) -> list[dict]:
        rows = []
        for k, vals in buckets.items():
            if len(vals) < 1:
                continue
            avg = sum(vals) / len(vals)
            rows.append({"value": k, "avg_score": round(avg, 2), "n": len(vals)})
        rows.sort(key=lambda r: r["avg_score"], reverse=True)
        return rows[:n]

    def _bottom(buckets: dict, n: int = 5) -> list[dict]:
        rows = []
        for k, vals in buckets.items():
            if len(vals) < 1:
                continue
            avg = sum(vals) / len(vals)
            if avg < median:
                rows.append({"value": k, "avg_score": round(avg, 2), "n": len(vals)})
        rows.sort(key=lambda r: r["avg_score"])
        return rows[:n]

    rollup["winning_hooks"] = _top(hook_buckets)
    rollup["losing_hooks"] = _bottom(hook_buckets)
    rollup["winning_angles"] = _top(angle_buckets)
    rollup["losing_angles"] = _bottom(angle_buckets)
    rollup["winning_publish_hours"] = sorted(
        hour_buckets.keys(),
        key=lambda h: sum(hour_buckets[h]) / len(hour_buckets[h]),
        reverse=True,
    )[:6]

    winners = [p for s, p in scored if s >= median][:3]
    rollup["lessons"] = [
        f"Top Short '{(p.get('title') or '')[:50]}' — {int((p.get('metrics') or {}).get('views', 0))} views"
        for p in winners
    ][:5]

    data["rollup"] = rollup
    save_strategy(data)
    return data
