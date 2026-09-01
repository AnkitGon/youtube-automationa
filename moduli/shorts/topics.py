"""Daily Shorts batch topic planner with dedup and diversity."""

from __future__ import annotations

import json
import re
from typing import Any

from moduli.ai_client import chat
from moduli.ai_validation import fetch_json_with_retries
from moduli.research import fetch_trending_block
from moduli.shorts.config import ShortsConfig, load_config
from moduli.shorts.history import find_duplicate, load_history, similarity
from moduli.shorts.strategy import guidance_block, load_strategy
from moduli.shared_learning import longform_topic_candidates


SHORTS_TOPIC_FIELDS = frozenset({
    "topic", "angle", "hook_hint", "source_type", "source_topic", "source_longform_video_id",
})


def _token_set(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def _diversity_penalty(candidate: dict, selected: list[dict]) -> float:
    if not selected:
        return 0.0
    penalty = 0.0
    ct = _token_set(candidate.get("topic", "") + " " + candidate.get("angle", ""))
    for s in selected:
        st = _token_set(s.get("topic", "") + " " + s.get("angle", ""))
        if not ct or not st:
            continue
        overlap = len(ct & st) / max(len(ct | st), 1)
        penalty += overlap
        if similarity(candidate.get("hook_hint", ""), s.get("hook_hint", "")) >= 0.7:
            penalty += 0.5
    return penalty


def _longform_angle_candidates() -> list[dict]:
    out: list[dict] = []
    try:
        from moduli.topic_history import load_topic_history
        from moduli.performance import carica_profili as load_lf_profiles

        history = load_topic_history()
        profiles = {p.get("video_id"): p for p in load_lf_profiles()}
        for entry in reversed(history[-30:]):
            vid = entry.get("video_id") or ""
            prof = profiles.get(vid, {})
            metrics = prof.get("metrics") or {}
            views = int(metrics.get("views") or 0)
            topic = (entry.get("topic") or entry.get("title") or "").strip()
            if not topic:
                continue
            out.append({
                "topic": topic,
                "angle": f"One decision that changed {topic[:40]}",
                "hook_hint": f"What {topic.split()[0]} got wrong",
                "source_type": "longform_angle",
                "source_topic": topic,
                "source_longform_video_id": vid,
                "_score": views,
            })
    except Exception:
        pass
    out.extend(longform_topic_candidates())
    out.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return out[:10]


def _evergreen_candidates(strategy: dict) -> list[dict]:
    rollup = (strategy.get("rollup") or {})
    angles = [a.get("value", a) if isinstance(a, dict) else a for a in rollup.get("winning_angles", [])]
    templates = [
        ("The one mistake everyone makes about {entity}", "contrarian_insight"),
        ("Why {entity} failed — the real reason", "failure_story"),
        ("What nobody tells you about {entity}", "hidden_truth"),
    ]
    entities = ["tech giants", "AI hype", "startup culture", "market bubbles"]
    if angles:
        entities = [str(a)[:40] for a in angles[:3]] + entities
    out = []
    for ent in entities[:4]:
        for tmpl, stype in templates:
            topic = tmpl.format(entity=ent)
            out.append({
                "topic": topic,
                "angle": topic,
                "hook_hint": topic.split("—")[0].strip()[:60],
                "source_type": stype,
                "source_topic": "",
                "source_longform_video_id": "",
            })
    return out


def _trending_candidates(strategy: dict) -> list[dict]:
    block = fetch_trending_block(strategy)
    if not block:
        return []
    try:
        raw = fetch_json_with_retries(
            lambda: chat(
                f"{block}\n\n"
                "Pick ONE timely educational Short concept for this channel. "
                "Return JSON only with keys: topic, angle, hook_hint, source_type (trending).",
                system="You are a YouTube Shorts strategist. JSON only, no markdown.",
                max_tokens=512,
                json_mode=True,
            ),
            required_fields=SHORTS_TOPIC_FIELDS - {"source_topic", "source_longform_video_id"},
            log_prefix="[shorts/topics]",
        )
        raw.setdefault("source_type", "trending")
        raw.setdefault("source_topic", "")
        raw.setdefault("source_longform_video_id", "")
        return [raw]
    except Exception as e:
        print(f"[shorts/topics] trending AI failed: {e}", flush=True)
        return []


def _historical_followup() -> list[dict]:
    entries = load_history().get("entries") or []
    winners = [e for e in entries if e.get("status") == "published"][-10:]
    out = []
    for e in reversed(winners):
        cat = e.get("source_type") or "evergreen"
        topic = e.get("topic") or ""
        if not topic:
            continue
        out.append({
            "topic": f"Another angle on {topic[:50]}",
            "angle": f"Follow-up: {e.get('angle', '')[:60]}",
            "hook_hint": f"Part 2 energy — {e.get('hook', '')[:40]}",
            "source_type": "historical_followup",
            "source_topic": topic,
            "source_longform_video_id": e.get("source_longform_video_id", ""),
        })
    return out[:3]


def _ai_batch_candidates(
    *,
    count: int,
    strategy: dict,
    trending_block: str,
    exclude: list[dict],
) -> list[dict]:
    exclude_txt = json.dumps(
        [{"topic": c.get("topic"), "angle": c.get("angle")} for c in exclude],
        ensure_ascii=False,
    )
    prompt = (
        f"{guidance_block(strategy)}\n\n"
        f"{trending_block}\n\n"
        f"Plan {count} DISTINCT YouTube Short concepts.\n"
        f"Already selected (do NOT repeat): {exclude_txt}\n\n"
        "Rules:\n"
        "- Each must be standalone (not a summary of a long video)\n"
        "- Different angles, hooks, and entities\n"
        "- Mix: trending, evergreen insight, long-form angle when possible\n"
        "Return JSON array of objects with keys: "
        "topic, angle, hook_hint, source_type, source_topic, source_longform_video_id."
    )
    try:
        raw = chat(prompt, system="YouTube Shorts planner. JSON array only.", max_tokens=2048, json_mode=True)
        data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        if isinstance(data, dict) and "concepts" in data:
            data = data["concepts"]
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            item.setdefault("source_type", "evergreen")
            item.setdefault("source_topic", "")
            item.setdefault("source_longform_video_id", "")
            if all(item.get(k) for k in ("topic", "angle", "hook_hint")):
                out.append(item)
        return out
    except Exception as e:
        print(f"[shorts/topics] AI batch failed: {e}", flush=True)
        return []


def plan_daily_batch(
    *,
    count: int | None = None,
    config: ShortsConfig | None = None,
) -> list[dict]:
    """Return up to `count` distinct Short concepts for today's batch."""
    cfg = config or load_config()
    count = count or cfg.per_day
    strategy = load_strategy()
    selected: list[dict] = []

    pools: list[tuple[str, list[dict]]] = [
        ("trending", _trending_candidates(strategy)),
        ("longform", _longform_angle_candidates()),
        ("evergreen", _evergreen_candidates(strategy)),
        ("historical", _historical_followup()),
    ]

    # Soft mix: try one from each preferred pool first
    preferred_order = ["trending", "evergreen", "longform", "historical"]
    for pool_name in preferred_order:
        if len(selected) >= count:
            break
        pool = next((p for name, p in pools if name == pool_name), [])
        for cand in pool:
            dup, _, reason = find_duplicate(
                topic=cand.get("topic", ""),
                angle=cand.get("angle", ""),
                hook=cand.get("hook_hint", ""),
                source_topic=cand.get("source_topic", ""),
            )
            if dup:
                continue
            if _diversity_penalty(cand, selected) >= 0.6:
                continue
            selected.append(cand)
            break

    # Fill remaining via scored pool merge + AI fallback
    if len(selected) < count:
        all_cands: list[tuple[float, dict]] = []
        for _, pool in pools:
            for cand in pool:
                dup, _, _ = find_duplicate(
                    topic=cand.get("topic", ""),
                    angle=cand.get("angle", ""),
                    hook=cand.get("hook_hint", ""),
                    source_topic=cand.get("source_topic", ""),
                )
                if dup:
                    continue
                score = cand.get("_score", 0) - _diversity_penalty(cand, selected) * 100
                all_cands.append((score, cand))
        all_cands.sort(key=lambda x: x[0], reverse=True)
        for _, cand in all_cands:
            if len(selected) >= count:
                break
            if any(c.get("topic") == cand.get("topic") and c.get("angle") == cand.get("angle") for c in selected):
                continue
            if _diversity_penalty(cand, selected) >= 0.6:
                continue
            selected.append(cand)

    if len(selected) < count:
        trending_block = fetch_trending_block(strategy)
        ai_more = _ai_batch_candidates(
            count=count - len(selected),
            strategy=strategy,
            trending_block=trending_block,
            exclude=selected,
        )
        for cand in ai_more:
            if len(selected) >= count:
                break
            dup, _, _ = find_duplicate(
                topic=cand.get("topic", ""),
                angle=cand.get("angle", ""),
                hook=cand.get("hook_hint", ""),
                source_topic=cand.get("source_topic", ""),
            )
            if dup or _diversity_penalty(cand, selected) >= 0.6:
                continue
            selected.append(cand)

    return selected[:count]
