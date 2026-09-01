"""
Ottimizzazione script da analytics — solo con evidenza sufficiente.

Impara durata, pacing, hook strength, story vs explainer, lunghezza frasi,
contesto e posizione CTA. Non cambia tutto ad ogni video.
"""

from __future__ import annotations

import os
import re
import statistics
from collections import defaultdict

from moduli.channel_confidence import confidence_from_profiles, confidence_prompt_block

MIN_SAMPLE_DEFAULT = int(os.environ.get("SCRIPT_MIN_SAMPLES", "3"))
MIN_CTR_DELTA = 0.0  # script usa retention, non CTR


def _min_samples(video_count: int) -> int:
    if video_count <= 4:
        return max(1, min(2, MIN_SAMPLE_DEFAULT))
    return MIN_SAMPLE_DEFAULT


def _retention(profile: dict) -> float:
    m = profile.get("metrics") or {}
    ret = float(m.get("retention_percent") or 0)
    if ret:
        return ret
    dur = max(float(m.get("duration_seconds") or 1), 1.0)
    return float(m.get("avg_view_duration_seconds") or 0) / dur * 100


def _duration_minutes(profile: dict) -> int | None:
    m = profile.get("metrics") or {}
    dur = m.get("duration_seconds")
    if not dur:
        return None
    return max(1, round(int(dur) / 60))


def extract_script_traits(script: str) -> dict:
    """Estrae caratteristiche script per learning futuro."""
    text = (script or "").strip()
    if not text:
        return {}

    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    word_counts = [len(s.split()) for s in sentences] if sentences else [0]
    avg_len = statistics.mean(word_counts) if word_counts else 0
    if avg_len < 12:
        sentence_length = "short"
    elif avg_len <= 20:
        sentence_length = "medium"
    else:
        sentence_length = "long"

    lower = text.lower()
    story_hits = len(re.findall(
        r"\b(in \d{4}|years ago|he |she |they |story|journey|once upon|narrative)\b", lower
    ))
    explainer_hits = len(re.findall(
        r"\b(let's explain|this means|essentially|in other words|definition|"
        r"simply put|to understand|break it down)\b", lower
    ))
    if story_hits > explainer_hits + 1:
        story_vs_explainer = "story"
    elif explainer_hits > story_hits + 1:
        story_vs_explainer = "explainer"
    else:
        story_vs_explainer = "mixed"

    words = text.split()
    opening_words = words[: max(1, len(words) // 5)]
    opening_text = " ".join(opening_words).lower()
    setup_markers = len(re.findall(
        r"\b(background|context|first|before we|historically|originally|founded|overview)\b",
        opening_text,
    ))
    if setup_markers >= 3:
        context_amount = "heavy"
    elif setup_markers >= 1:
        context_amount = "moderate"
    else:
        context_amount = "minimal"

    cta_pat = re.compile(
        r"\b(subscribe|like this video|comment below|hit the bell|smash that like|"
        r"follow for more|don't forget to)\b",
        re.I,
    )
    cta_positions = [m.start() / max(len(text), 1) for m in cta_pat.finditer(text)]
    if not cta_positions:
        cta_placement = "none"
    elif cta_positions[0] < 0.25:
        cta_placement = "early"
    elif cta_positions[0] > 0.75:
        cta_placement = "late"
    else:
        cta_placement = "mid"

    return {
        "sentence_length": sentence_length,
        "avg_sentence_words": round(avg_len, 1),
        "story_vs_explainer": story_vs_explainer,
        "context_amount": context_amount,
        "cta_placement": cta_placement,
    }


def _bucket_rows(profiles: list[dict], key_fn) -> dict[str, list[float]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for p in profiles:
        keys = key_fn(p)
        if not keys:
            continue
        ret = _retention(p)
        if isinstance(keys, str):
            keys = [keys]
        for k in keys:
            if k:
                buckets[k].append(ret)
    return buckets


def _rank_buckets(
    buckets: dict[str, list[float]],
    baseline: float,
    min_n: int,
) -> list[dict]:
    rows: list[dict] = []
    for value, vals in buckets.items():
        if len(vals) < min_n:
            continue
        avg = statistics.mean(vals)
        rows.append({
            "value": value,
            "sample_size": len(vals),
            "avg_retention": round(avg, 1),
            "retention_vs_channel": round(avg - baseline, 1),
            "confidence": "high" if len(vals) >= MIN_SAMPLE_DEFAULT + 1 else "medium",
        })
    rows.sort(key=lambda x: x["retention_vs_channel"], reverse=True)
    return rows


def analyze_script_optimization(profiles: list[dict]) -> dict:
    """Analizza pattern script ↔ retention. Raccomandazioni solo con evidenza."""
    empty = {
        "has_data": False,
        "sufficient_evidence": False,
        "video_count": 0,
        "recommendations": [],
        "insufficient_data_notes": [],
        "suggested": {},
        "channel_baseline": {},
    }
    usable = [p for p in profiles if _retention(p) > 0 or (p.get("metrics") or {}).get("views")]
    if not usable:
        return empty

    min_n = _min_samples(len(usable))
    conf = confidence_from_profiles(usable)
    if conf.apply_learning:
        min_n = max(min_n, conf.min_bucket_samples)
    retentions = [_retention(p) for p in usable]
    baseline = statistics.mean(retentions)

    def _meta_val(p: dict, key: str) -> str:
        meta = p.get("content_metadata") or {}
        traits = meta.get("script_traits") or {}
        return (traits.get(key) or meta.get(key) or "").strip()

    dimensions: list[tuple[str, callable]] = [
        ("ideal_duration_min", lambda p: str(_duration_minutes(p) or "")),
        ("pacing", lambda p: _meta_val(p, "pacing")),
        ("hook_strength", lambda p: _meta_val(p, "hook_strength")),
        ("story_vs_explainer", lambda p: _meta_val(p, "story_vs_explainer")),
        ("sentence_length", lambda p: _meta_val(p, "sentence_length")),
        ("context_amount", lambda p: _meta_val(p, "context_amount")),
        ("cta_placement", lambda p: _meta_val(p, "cta_placement")),
    ]

    recommendations: list[dict] = []
    insufficient: list[str] = []
    suggested: dict = {}

    for dim, key_fn in dimensions:
        buckets = _bucket_rows(usable, key_fn)
        buckets = {k: v for k, v in buckets.items() if k and k != "none"}
        ranked = _rank_buckets(buckets, baseline, min_n)
        if ranked and ranked[0]["retention_vs_channel"] >= 2:
            top = ranked[0]
            recommendations.append({
                "dimension": dim,
                "value": top["value"],
                "sample_size": top["sample_size"],
                "avg_retention": top["avg_retention"],
                "retention_vs_channel": top["retention_vs_channel"],
                "confidence": top["confidence"],
            })
        elif buckets:
            insufficient.append(
                f"{dim}: not enough consistent data (need {min_n}+ videos per variant)"
            )
        else:
            insufficient.append(f"{dim}: no script metadata recorded yet")

    # Suggerimenti conservativi — solo dimensioni con evidenza alta/media e delta >= 3
    for rec in recommendations:
        if rec["retention_vs_channel"] < 3:
            continue
        dim, val = rec["dimension"], rec["value"]
        if dim == "ideal_duration_min" and val.isdigit():
            suggested["target_minutes"] = int(val)
        elif dim == "pacing" and val in ("slow", "medium", "fast"):
            suggested["pacing"] = val
        elif dim == "hook_strength" and val in ("soft", "medium", "aggressive"):
            suggested["hook_strength"] = val

    sufficient = (
        conf.apply_learning
        and any(
            r["sample_size"] >= min_n and r["retention_vs_channel"] >= 3
            for r in recommendations
        )
    )

    return {
        "has_data": True,
        "sufficient_evidence": sufficient,
        "video_count": len(usable),
        "confidence": conf.level,
        "optimization_mode": conf.optimization_mode,
        "min_samples_required": min_n,
        "recommendations": recommendations[:8],
        "insufficient_data_notes": insufficient[:6],
        "suggested": suggested,
        "channel_baseline": {"avg_retention": round(baseline, 1)},
    }


def script_guidance_block(strategy: dict | None = None, pref: dict | None = None) -> str:
    """Blocco prompt script — cambia solo ciò che i dati supportano."""
    if strategy is None:
        strategy = {}
    pref = pref or {}
    try:
        from moduli.performance import carica_profili
        profiles = carica_profili()
    except Exception:
        profiles = []

    analysis = analyze_script_optimization(profiles)
    lines = [
        confidence_prompt_block(profiles=profiles),
        "SCRIPT OPTIMIZATION (evidence-based — do NOT change everything every video):",
        "Keep the current strategy defaults unless a channel learning below is backed by enough data.",
    ]

    if not analysis.get("has_data"):
        lines.append("- Insufficient published videos — use strategy pacing/duration as-is.")
        strategy["_script_suggestions"] = {}
        return "\n".join(lines)

    base = analysis.get("channel_baseline") or {}
    lines.append(f"- Channel avg retention: {base.get('avg_retention', 0)}%")

    if analysis.get("sufficient_evidence"):
        for rec in analysis.get("recommendations") or []:
            if rec["retention_vs_channel"] < 2:
                continue
            dim_label = rec["dimension"].replace("_", " ")
            lines.append(
                f"- LEARNED ({rec['confidence']} confidence, n={rec['sample_size']}): "
                f"{dim_label} = {rec['value']} "
                f"(+{rec['retention_vs_channel']:.0f}% retention vs channel)"
            )
    else:
        lines.append(
            f"- Not enough evidence yet (need {analysis.get('min_samples_required', 3)}+ "
            "videos per pattern) — keep current pacing, duration, and structure."
        )

    for note in (analysis.get("insufficient_data_notes") or [])[:3]:
        lines.append(f"- {note}")

    suggested = analysis.get("suggested") or {}
    strategy["_script_suggestions"] = suggested

    if suggested.get("target_minutes"):
        lines.append(
            f"- For THIS video: consider ~{suggested['target_minutes']} min "
            "(data-supported; override only if topic demands otherwise)"
        )
    if suggested.get("pacing"):
        lines.append(f"- For THIS video: pacing = {suggested['pacing']} (data-supported)")
    if suggested.get("hook_strength"):
        lines.append(f"- For THIS video: hook_strength = {suggested['hook_strength']} (data-supported)")

    lines.append(
        "- Do NOT rewrite structure entirely — apply only the evidence-backed tweaks above."
    )
    return "\n".join(lines)


def apply_script_suggestions(strategy: dict, pref: dict) -> dict:
    """Applica suggerimenti conservativi a strategy (non sovrascrive valori espliciti)."""
    suggestions = strategy.get("_script_suggestions") or {}
    out = dict(strategy)
    if suggestions.get("target_minutes") and out.get("target_minutes") is None:
        out["target_minutes"] = suggestions["target_minutes"]
    if suggestions.get("pacing") and not out.get("pacing"):
        out["pacing"] = suggestions["pacing"]
    if suggestions.get("hook_strength") and not out.get("hook_strength"):
        out["hook_strength"] = suggestions["hook_strength"]
    return out
