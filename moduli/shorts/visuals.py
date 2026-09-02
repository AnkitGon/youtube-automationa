"""Per-segment visual acquisition for Shorts."""

from __future__ import annotations

import os
import re
import time

from moduli.asset import scarica_clips
from moduli.shorts.config import ShortsConfig, load_config

_GENERIC_QUERY_RE = re.compile(
    r"\b(abstract|concept|innovation|digital transformation|technology background|"
    r"business concept|futuristic|generic|b-roll|stock footage)\b",
    re.I,
)
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "your", "they", "their",
    "about", "into", "over", "under", "when", "what", "how", "why", "are", "was",
})
_VAGUE_WORDS = frozenset({
    "technology", "tech", "trends", "trend", "emerging", "future", "futuristic",
    "digital", "innovation", "innovative", "business", "data", "concept", "abstract",
    "generic", "modern", "new", "latest", "world", "industry", "sector", "market",
    "ai", "artificial", "intelligence", "transformation", "solution", "solutions",
})
_CONCRETE_FALLBACKS = (
    ("smartphone", "closeup hand"),
    ("laptop", "typing keyboard"),
    ("server room", "data center"),
    ("office", "meeting room"),
    ("factory", "assembly line"),
    ("engineer", "circuit board"),
    ("scientist", "laboratory microscope"),
    ("city skyline", "night lights"),
)


def _tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) > 2 and w not in _STOPWORDS
    }


def _is_generic_query(query: str) -> bool:
    q = (query or "").strip().lower()
    if not q or len(q) < 4:
        return True
    if _GENERIC_QUERY_RE.search(q):
        return True
    # single vague word
    return len(q.split()) == 1 and q in {"technology", "business", "digital", "data", "ai"}


def _derive_concrete_keywords(text: str, intent: str = "") -> list[str]:
    """Build Pexels-friendly keywords from narration when the model outputs vague terms."""
    blob = f"{intent} {text}"
    words = re.findall(r"[A-Za-z0-9]+", blob)
    candidates: list[str] = []

    content = [w for w in words if len(w) > 2 and w.lower() not in _STOPWORDS and w.lower() not in _VAGUE_WORDS]
    if len(content) >= 2:
        candidates.append(" ".join(content[:2]).lower())
        candidates.append(" ".join(content[-2:]).lower())
    if len(content) >= 4:
        mid = len(content) // 2
        candidates.append(" ".join(content[mid : mid + 2]).lower())

    for w in words:
        if len(w) > 3 and w[0].isupper() and w.lower() not in _VAGUE_WORDS:
            candidates.append(w.lower())

    unique: list[str] = []
    for c in candidates:
        c = " ".join(c.split())
        if c and not _is_generic_query(c) and c not in unique:
            unique.append(c)
    return unique[:4]


def refine_segment_visuals(segment: dict, *, segment_index: int = 0) -> dict:
    """Replace vague keywords with concrete search terms derived from narration."""
    seg = dict(segment or {})
    raw = [str(k).strip() for k in (seg.get("keywords") or []) if str(k).strip()]
    good = [k for k in raw if not _is_generic_query(k)]

    derived = _derive_concrete_keywords(seg.get("text") or "", seg.get("visual_intent") or "")
    for d in derived:
        if d not in good:
            good.append(d)

    if len(good) < 2:
        fb_a, fb_b = _CONCRETE_FALLBACKS[segment_index % len(_CONCRETE_FALLBACKS)]
        for fb in (fb_a, fb_b):
            if fb not in good:
                good.append(fb)

    seg["keywords"] = good[:4]
    if not (seg.get("visual_intent") or "").strip():
        seg["visual_intent"] = f"{good[0]} {good[1] if len(good) > 1 else 'closeup'}"
    return seg


def refine_visual_segments(content: dict) -> dict:
    """Auto-fix abstract stock keywords before validation/render."""
    out = dict(content)
    segments = out.get("visual_segments") or []
    if not isinstance(segments, list):
        return out
    out["visual_segments"] = [
        refine_segment_visuals(seg, segment_index=i) if isinstance(seg, dict) else seg
        for i, seg in enumerate(segments)
    ]
    return out


def segment_search_ready(segment: dict) -> bool:
    """True if we can build at least one concrete Pexels query for this segment."""
    return len(_build_search_queries(segment)) > 0


def _build_search_queries(segment: dict) -> list[str]:
    """Concrete Pexels queries, most specific first."""
    seen: set[str] = set()
    queries: list[str] = []

    def _add(raw: str) -> None:
        q = " ".join((raw or "").split()).strip()
        key = q.lower()
        if not q or key in seen or _is_generic_query(q):
            return
        seen.add(key)
        queries.append(q)

    intent = (segment.get("visual_intent") or "").strip()
    keywords = [str(k).strip() for k in (segment.get("keywords") or []) if str(k).strip()]
    text = (segment.get("text") or "").strip()

    if keywords:
        _add(" ".join(keywords[:3]))
        for kw in keywords[:4]:
            _add(kw)

    if intent:
        _add(intent)

    # Derive from narration line — last concrete phrase
    if text:
        words = [w for w in re.findall(r"[A-Za-z0-9]+", text) if w.lower() not in _STOPWORDS]
        if len(words) >= 2:
            _add(" ".join(words[-3:]))
        if len(words) >= 4:
            _add(" ".join(words[:3]))

    if not queries:
        _add("office laptop closeup")

    return queries[:5]


def _download_clips_with_retry(query: str, *, max_n: int, orientation: str) -> list[str]:
    """Pexels downloads can drop mid-stream — retry before giving up."""
    attempts = max(1, int(os.environ.get("PEXELS_DOWNLOAD_RETRIES", "3")))
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return scarica_clips(query, max_n=max_n, orientation=orientation)
        except Exception as e:
            last_err = e
            if attempt >= attempts:
                break
            wait = min(15, 3 * attempt)
            print(
                f"[shorts/visuals] Pexels retry {attempt}/{attempts} for '{query}' "
                f"({type(e).__name__}) in {wait}s",
                flush=True,
            )
            time.sleep(wait)
    raise last_err or RuntimeError(f"Pexels download failed for '{query}'")


def _score_clip_query(segment: dict, query: str) -> int:
    """Higher = better semantic match between segment narration and search query."""
    seg_tokens = _tokens(segment.get("text") or "")
    seg_tokens |= _tokens(segment.get("visual_intent") or "")
    for kw in segment.get("keywords") or []:
        seg_tokens |= _tokens(str(kw))
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0
    overlap = len(seg_tokens & query_tokens)
    return overlap * 10 + min(len(query_tokens), 4)


def acquire_segment_clips(
    visual_segments: list[dict],
    *,
    config: ShortsConfig | None = None,
) -> list[dict]:
    """
    Download portrait clips per visual segment.
    Returns list of {segment_index, clip_path, duration, text, keywords, visual_intent}.
    """
    cfg = config or load_config()
    os.makedirs(cfg.cache_dir, exist_ok=True)
    results: list[dict] = []
    used_paths: set[str] = set()

    for i, seg in enumerate(visual_segments):
        if not isinstance(seg, dict):
            continue

        duration = float(seg.get("duration_hint") or 3.0)
        duration = max(cfg.segment_min_seconds, min(cfg.segment_max_seconds, duration))

        clip_path = None
        queries = sorted(_build_search_queries(seg), key=lambda q: -_score_clip_query(seg, q))

        for query in queries:
            try:
                paths = _download_clips_with_retry(query, max_n=4, orientation="portrait")
                for path in paths:
                    if path and path not in used_paths:
                        clip_path = path
                        used_paths.add(path)
                        print(
                            f"[shorts/visuals] seg {i}: '{query}' -> {os.path.basename(path)}",
                            flush=True,
                        )
                        break
                if clip_path:
                    break
            except Exception as e:
                print(f"[shorts/visuals] Pexels skip seg {i} '{query}': {e}", flush=True)

        # Landscape fallback only if portrait search failed
        if not clip_path:
            for query in queries[:2]:
                try:
                    paths = _download_clips_with_retry(query, max_n=3, orientation="landscape")
                    for path in paths:
                        if path and path not in used_paths:
                            clip_path = path
                            used_paths.add(path)
                            print(
                                f"[shorts/visuals] seg {i}: landscape fallback '{query}'",
                                flush=True,
                            )
                            break
                    if clip_path:
                        break
                except Exception:
                    continue

        results.append({
            "segment_index": i,
            "clip_path": clip_path,
            "duration": duration,
            "text": seg.get("text") or "",
            "keywords": seg.get("keywords") or [],
            "visual_intent": seg.get("visual_intent") or "",
        })

    return results
