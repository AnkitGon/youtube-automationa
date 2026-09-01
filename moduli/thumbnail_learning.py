"""
Apprendimento thumbnail da CTR — solo con dati sufficienti.

Analizza concept, soggetto, inquadratura, stile, contrasto e phrase style.
Non dichiara successi senza evidenza statistica.
"""

from __future__ import annotations

import os
import re
import statistics
from collections import defaultdict

from moduli.channel_confidence import (
    confidence_from_profiles,
    confidence_prompt_block,
    should_claim_pattern,
)

MIN_SAMPLE_DEFAULT = int(os.environ.get("THUMBNAIL_MIN_SAMPLES", "3"))
MIN_CTR_DELTA = float(os.environ.get("THUMBNAIL_MIN_CTR_DELTA", "0.8"))


def _min_samples(video_count: int) -> int:
    if video_count <= 4:
        return max(2, min(2, MIN_SAMPLE_DEFAULT))
    return MIN_SAMPLE_DEFAULT


def _ctr(profile: dict) -> float:
    return float((profile.get("metrics") or {}).get("ctr_percent") or 0)


def classify_thumbnail_traits(
    description: str = "",
    phrase: str = "",
    mood: str = "",
) -> dict:
    """Classifica caratteristiche visive da prompt thumbnail + phrase."""
    text = f"{description} {phrase} {mood}".lower()
    traits: dict[str, str] = {}

    if re.search(r"\b(face|portrait|person|man|woman|human|expression|eyes)\b", text):
        traits["subject_type"] = "human_face"
    elif re.search(r"\b(chip|logo|phone|device|robot|server|object|product)\b", text):
        traits["subject_type"] = "object"
    elif re.search(r"\b(abstract|gradient|pattern|glow|neural)\b", text):
        traits["subject_type"] = "abstract"
    else:
        traits["subject_type"] = "scene"

    if re.search(r"close[- ]?up|tight (shot|frame)|facial|macro", text):
        traits["shot_type"] = "close_up"
    elif re.search(r"wide (shot|angle)|panoramic|landscape|cityscape|aerial", text):
        traits["shot_type"] = "wide"
    else:
        traits["shot_type"] = "medium"

    if re.search(r"dramatic|moody|dark|high contrast|bold|intense|cinematic", text):
        traits["visual_style"] = "dramatic"
    elif re.search(r"clean|minimal|simple|bright|flat|white background", text):
        traits["visual_style"] = "clean"
    else:
        traits["visual_style"] = "balanced"

    elements = len(re.findall(
        r"\b(foreground|background|subject|layer|element|object|figure|text)\b", text
    ))
    if elements >= 5:
        traits["visual_elements"] = "busy"
    elif elements >= 2:
        traits["visual_elements"] = "few"
    else:
        traits["visual_elements"] = "single"

    phrase_clean = (phrase or "").strip()
    if not phrase_clean:
        traits["phrase_style"] = "none"
    elif phrase_clean.isupper() and len(phrase_clean.split()) <= 3:
        traits["phrase_style"] = "short_caps"
    else:
        traits["phrase_style"] = "long"

    if re.search(r"high contrast|bold color|vivid|saturated|neon|striking", text):
        traits["contrast"] = "high"
    elif re.search(r"muted|soft|pastel|low contrast|subtle", text):
        traits["contrast"] = "low"
    else:
        traits["contrast"] = "medium"

    return traits


def _profile_traits(profile: dict) -> dict:
    meta = profile.get("content_metadata") or {}
    stored = meta.get("thumbnail_traits") or {}
    if stored:
        return stored
    return classify_thumbnail_traits(
        meta.get("thumbnail_description_snippet") or "",
        meta.get("thumbnail_concept") or "",
        meta.get("mood") or "",
    )


def analyze_thumbnail_patterns(profiles: list[dict]) -> dict:
    """Correla tratti thumbnail con CTR — claim successo solo con evidenza."""
    empty = {
        "has_data": False,
        "sufficient_evidence": False,
        "video_count": 0,
        "patterns": [],
        "winning_traits": [],
        "losing_traits": [],
        "insufficient_data_notes": [],
        "channel_baseline": {},
    }
    usable = [p for p in profiles if (p.get("title") or "").strip() and _ctr(p) >= 0]
    if not usable:
        return empty

    min_n = _min_samples(len(usable))
    conf = confidence_from_profiles(usable)
    if not conf.apply_learning:
        min_n = 99
    elif conf.apply_learning:
        min_n = max(min_n, conf.min_bucket_samples)
    ctrs = [_ctr(p) for p in usable]
    baseline = statistics.mean(ctrs) if ctrs else 0.0

    trait_buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for p in usable:
        traits = _profile_traits(p)
        ctr = _ctr(p)
        for dim, val in traits.items():
            if val:
                trait_buckets[(dim, val)].append(ctr)

    pattern_rows: list[dict] = []
    for (dim, val), vals in trait_buckets.items():
        row = {
            "dimension": dim,
            "value": val,
            "sample_size": len(vals),
            "avg_ctr": round(statistics.mean(vals), 2),
            "ctr_vs_channel": round(statistics.mean(vals) - baseline, 2),
        }
        pattern_rows.append(row)

    pattern_rows.sort(key=lambda x: x["ctr_vs_channel"], reverse=True)

    winning, losing, insufficient = [], [], []
    for row in pattern_rows:
        if not should_claim_pattern(row["sample_size"], len(usable)):
            insufficient.append(
                f"{row['dimension']}={row['value']}: only n={row['sample_size']} "
                f"(need {min_n}+ at {conf.level} confidence)"
            )
            continue
        if row["ctr_vs_channel"] >= MIN_CTR_DELTA:
            row["confidence"] = "high" if row["sample_size"] >= MIN_SAMPLE_DEFAULT + 1 else "medium"
            winning.append(row)
        elif row["ctr_vs_channel"] <= -MIN_CTR_DELTA:
            losing.append(row)

    sufficient = len(winning) >= 1 and any(w["sample_size"] >= min_n for w in winning)

    return {
        "has_data": True,
        "sufficient_evidence": sufficient and conf.apply_learning,
        "video_count": len(usable),
        "confidence": conf.level,
        "min_samples_required": min_n,
        "patterns": pattern_rows,
        "winning_traits": winning[:8],
        "losing_traits": losing[:6],
        "insufficient_data_notes": insufficient[:8],
        "channel_baseline": {"avg_ctr": round(baseline, 2)},
    }


def thumbnail_guidance_block(strategy: dict | None = None) -> str:
    """Guida per thumbnail_description — solo tratti supportati dai dati."""
    if strategy is None:
        strategy = {}
    try:
        from moduli.performance import carica_profili
        profiles = carica_profili()
    except Exception:
        profiles = []

    analysis = analyze_thumbnail_patterns(profiles)
    style = (strategy.get("thumbnail_style") or "").strip()

    lines = [
        confidence_prompt_block(profiles=profiles),
        "THUMBNAIL LEARNING (CTR-based — only apply patterns with sufficient channel data):",
    ]
    if style:
        lines.append(f"- User/strategy thumbnail_style: {style[:200]}")

    if not analysis.get("has_data"):
        lines.append(
            "- Insufficient data — use bold contrast, single focal subject, no text in image. "
            "Do NOT claim any style is proven yet."
        )
        try:
            from moduli.avoid_patterns import avoid_prompt_section
            avoid = avoid_prompt_section(strategy, stage="thumbnail")
            if avoid:
                lines.append(avoid)
        except Exception:
            pass
        strategy["_thumbnail_guidance"] = {"sufficient_evidence": False}
        return "\n".join(lines)

    base = analysis.get("channel_baseline") or {}
    lines.append(f"- Channel avg CTR: {base.get('avg_ctr', 0)}%")

    if not analysis.get("sufficient_evidence"):
        lines.append(
            f"- NOT ENOUGH DATA to claim winning thumbnail styles "
            f"(need {analysis.get('min_samples_required', 3)}+ videos per trait). "
            "Use strong contrast and one clear subject — do not copy unproven patterns."
        )
        for note in (analysis.get("insufficient_data_notes") or [])[:3]:
            lines.append(f"- {note}")
        try:
            from moduli.avoid_patterns import avoid_prompt_section
            avoid = avoid_prompt_section(strategy, stage="thumbnail")
            if avoid:
                lines.append(avoid)
        except Exception:
            pass
        strategy["_thumbnail_guidance"] = {"sufficient_evidence": False}
        return "\n".join(lines)

    lines.append("Proven CTR patterns on this channel (use in thumbnail_description):")
    for w in analysis.get("winning_traits") or []:
        lines.append(
            f"- {w['dimension']} = {w['value']}: CTR {w['avg_ctr']}% "
            f"({w['ctr_vs_channel']:+.1f} vs channel, n={w['sample_size']}, "
            f"{w.get('confidence', 'medium')} confidence)"
        )

    if analysis.get("losing_traits"):
        lines.append("Avoid or use sparingly (underperformed CTR):")
        for lp in analysis["losing_traits"][:3]:
            lines.append(
                f"- {lp['dimension']} = {lp['value']} "
                f"({lp['ctr_vs_channel']:+.1f}% CTR vs channel)"
            )

    lines.append(
        "- thumbnail_description: incorporate proven traits above; "
        "single focal subject, high contrast, NO text in the image."
    )
    try:
        from moduli.avoid_patterns import avoid_prompt_section
        avoid = avoid_prompt_section(strategy, stage="thumbnail")
        if avoid:
            lines.append(avoid)
    except Exception:
        pass
    strategy["_thumbnail_guidance"] = {
        "sufficient_evidence": True,
        "winning_traits": analysis.get("winning_traits") or [],
    }
    return "\n".join(lines)
