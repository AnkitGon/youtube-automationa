"""Per-segment visual acquisition for Shorts."""

from __future__ import annotations

import os
import re

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
                paths = scarica_clips(query, max_n=4, orientation="portrait")
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
                    paths = scarica_clips(query, max_n=3, orientation="landscape")
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
