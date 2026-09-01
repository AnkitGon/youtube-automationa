"""
Livello di confidenza canale basato su dimensione campione.

Evita overfitting su pochi video:
  1-2  → LOW    (strategia standard)
  3-5  → MEDIUM (segnali deboli)
  6-9  → MEDIUM+ (ottimizzazione più forte)
  10+  → HIGH   (ottimizzazione aggressiva consentita)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelConfidence:
    video_count: int
    level: str  # LOW | MEDIUM | HIGH
    score: float  # 0.0–1.0
    optimization_mode: str  # standard | weak_signals | strong | aggressive
    min_bucket_samples: int
    apply_learning: bool
    apply_publish_changes: bool
    summary: str


def channel_confidence(video_count: int) -> ChannelConfidence:
    n = max(0, int(video_count))
    if n <= 2:
        return ChannelConfidence(
            video_count=n,
            level="LOW",
            score=0.25 if n <= 1 else 0.35,
            optimization_mode="standard",
            min_bucket_samples=99,  # praticamente nessun pattern claim
            apply_learning=False,
            apply_publish_changes=False,
            summary=(
                f"{n} video — use mostly standard strategy; "
                "do not change channel formula from one-off results."
            ),
        )
    if n <= 5:
        return ChannelConfidence(
            video_count=n,
            level="MEDIUM",
            score=0.45 + (n - 3) * 0.05,
            optimization_mode="weak_signals",
            min_bucket_samples=2,
            apply_learning=True,
            apply_publish_changes=False,
            summary=(
                f"{n} videos — weak signals only; prefer defaults unless a pattern "
                "has multiple supporting videos."
            ),
        )
    if n <= 9:
        return ChannelConfidence(
            video_count=n,
            level="MEDIUM",
            score=0.6 + (n - 6) * 0.04,
            optimization_mode="strong",
            min_bucket_samples=2,
            apply_learning=True,
            apply_publish_changes=True,
            summary=(
                f"{n} videos — stronger optimization allowed; still require "
                "multiple videos per pattern before major shifts."
            ),
        )
    return ChannelConfidence(
        video_count=n,
        level="HIGH",
        score=min(0.95, 0.75 + (n - 10) * 0.02),
        optimization_mode="aggressive",
        min_bucket_samples=3,
        apply_learning=True,
        apply_publish_changes=True,
        summary=(
            f"{n} videos — confident enough for aggressive optimization; "
            "still never pivot on a single outlier video."
        ),
    )


def confidence_from_profiles(profiles: list | None) -> ChannelConfidence:
    if not profiles:
        return channel_confidence(0)
    usable = [p for p in profiles if (p.get("title") or p.get("video_id"))]
    return channel_confidence(len(usable))


def effective_min_samples(base_min: int, video_count: int) -> int:
    """Alza la soglia campione quando la confidenza è bassa."""
    conf = channel_confidence(video_count)
    if not conf.apply_learning:
        return max(base_min, 99)
    return max(base_min, conf.min_bucket_samples)


def should_claim_pattern(sample_size: int, video_count: int, min_delta: float = 0) -> bool:
    """True solo se il bucket ha abbastanza evidenza per il livello corrente."""
    conf = channel_confidence(video_count)
    if not conf.apply_learning:
        return False
    if sample_size < conf.min_bucket_samples:
        return False
    # Un solo video vincente non basta su canali piccoli
    if video_count <= 5 and sample_size < 2:
        return False
    return True


def confidence_prompt_block(video_count: int | None = None, profiles: list | None = None) -> str:
    conf = confidence_from_profiles(profiles) if profiles is not None else channel_confidence(video_count or 0)
    return (
        f"CHANNEL CONFIDENCE: {conf.level} ({conf.video_count} videos, mode={conf.optimization_mode})\n"
        f"{conf.summary}\n"
        "A single successful video must NOT reshape the entire channel strategy."
    )


def confidence_dict(conf: ChannelConfidence | None = None, profiles: list | None = None) -> dict:
    c = conf or confidence_from_profiles(profiles)
    return {
        "video_count": c.video_count,
        "level": c.level,
        "score": round(c.score, 3),
        "optimization_mode": c.optimization_mode,
        "min_bucket_samples": c.min_bucket_samples,
        "apply_learning": c.apply_learning,
        "apply_publish_changes": c.apply_publish_changes,
        "summary": c.summary,
    }
