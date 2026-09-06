"""Hook-first Short script generation and validation."""

from __future__ import annotations

import re

from moduli.ai_client import chat
from moduli.ai_validation import fetch_json_with_retries
from moduli.content_quality import detect_ai_filler
from moduli.narration_quality import narration_prompt_block, validate_spoken_narration
from moduli.research import build_research_brief
from moduli.shorts.config import ShortsConfig, load_config
from moduli.shorts.history import find_duplicate, is_summary_of
from moduli.shorts.strategy import guidance_block, load_strategy
from moduli.hashtags import fix_spaced_hashtags, normalize_hashtags
from moduli.shorts.visuals import refine_visual_segments, segment_search_ready

SHORTS_CONTENT_FIELDS = frozenset({
    "title", "hook", "script", "angle", "key_claims", "payoff",
    "description", "tags", "hashtags", "visual_segments",
    "target_duration_seconds", "source_type", "cta",
})

_BANNED_OPENERS = (
    r"^hey\s+(guys|everyone)",
    r"^welcome\s+back",
    r"^in\s+today'?s\s+video",
    r"^let'?s\s+dive\s+in",
)


def _word_count(script: str) -> int:
    return len((script or "").split())


def _duration_from_words(words: int, wps: float = 2.5) -> float:
    return words / wps


def _ensure_script_starts_with_hook(content: dict) -> dict:
    """Prepend hook to script when the model separated them."""
    hook = (content.get("hook") or "").strip()
    script = (content.get("script") or "").strip()
    if not hook or not script:
        return content
    if script.lower().startswith(hook.lower()[:20]):
        return content
    if hook.lower() in script.lower()[:80]:
        return content
    out = dict(content)
    joiner = "" if hook.endswith((".", "!", "?")) else ". "
    out["script"] = f"{hook}{joiner}{script}"
    return out


def _validate_structure(content: dict, cfg: ShortsConfig) -> list[str]:
    errors: list[str] = []
    script = (content.get("script") or "").strip()
    hook = (content.get("hook") or "").strip()
    title = (content.get("title") or "").strip()

    if not hook:
        errors.append("missing hook")
    if len(title) > 70:
        errors.append(f"title too long ({len(title)} chars)")
    if not script.lower().startswith(hook.lower()[:20]):
        # Hook should open the script
        if hook.lower() not in script.lower()[:80]:
            errors.append("script must open with the hook")

    words = _word_count(script)
    est_dur = _duration_from_words(words)
    if est_dur < cfg.min_duration * 0.85:
        errors.append(f"script too short (~{est_dur:.0f}s, min {cfg.min_duration}s)")
    if est_dur > cfg.max_duration * 1.15:
        errors.append(f"script too long (~{est_dur:.0f}s, max {cfg.max_duration}s)")

    for pat in _BANNED_OPENERS:
        if re.search(pat, script, re.I):
            errors.append("banned opener phrase")
            break

    filler = detect_ai_filler(script)
    if len(filler) >= 2:
        errors.extend(filler[:2])

    segments = content.get("visual_segments") or []
    if not segments or not isinstance(segments, list):
        errors.append("missing visual_segments")
    elif len(segments) < 2:
        errors.append("need at least 2 visual segments")
    else:
        for i, seg in enumerate(segments):
            if not isinstance(seg, dict):
                errors.append(f"segment {i}: invalid")
                continue
            kws = seg.get("keywords") or []
            if len(kws) < 2:
                errors.append(f"segment {i}: need at least 2 concrete keywords")
            elif not segment_search_ready(seg):
                errors.append(f"segment {i}: no concrete stock search terms")
            text = (seg.get("text") or "").strip()
            if len(text.split()) < 3:
                errors.append(f"segment {i}: text too short — tie to narration line")

    return errors


def run_shorts_content_gate(content: dict, concept: dict, cfg: ShortsConfig | None = None) -> tuple[bool, list[str]]:
    """Pre-render content validation."""
    cfg = cfg or load_config()
    errors = _validate_structure(content, cfg)

    topic = concept.get("topic") or content.get("title") or ""
    source_topic = concept.get("source_topic") or ""

    dup, matched, reason = find_duplicate(
        topic=topic,
        angle=content.get("angle") or concept.get("angle", ""),
        hook=content.get("hook", ""),
        title=content.get("title", ""),
        script=content.get("script", ""),
        source_topic=source_topic,
    )
    if dup:
        errors.append(f"dedup: {reason} ({matched[:40]})")

    if source_topic and is_summary_of(source_topic, content.get("title", "") + " " + content.get("script", "")):
        errors.append("lazy summary of long-form topic")

    # Relaxed viewer value for shorts (shorter scripts)
    script = content.get("script") or ""
    if _word_count(script) < 40:
        errors.append("script too thin for viewer value")
    elif len(detect_ai_filler(script)) >= 3:
        errors.append("too much AI filler")

    n_ok, n_errors, _ = validate_spoken_narration(script, fmt="short")
    if not n_ok:
        errors.extend(n_errors[:2])

    return len(errors) == 0, errors


def generate_short_content(concept: dict, *, config: ShortsConfig | None = None) -> dict:
    """Generate and validate Short content JSON for one concept."""
    cfg = config or load_config()
    strategy = load_strategy()
    topic = concept.get("topic") or "technology insight"
    brief = build_research_brief(topic, max_snippets=4)
    min_words = int(cfg.min_duration * 2.5)
    max_words = int(cfg.max_duration * 2.5)

    system = (
        "You write viral educational YouTube Shorts scripts. "
        "Return ONLY valid JSON. No markdown, no reasoning."
    )
    prompt = (
        f"{guidance_block(strategy)}\n\n"
        f"{narration_prompt_block('short')}\n\n"
        f"{brief.get('prompt_block', '')}\n\n"
        f"CONCEPT:\n"
        f"- Topic: {concept.get('topic')}\n"
        f"- Angle: {concept.get('angle')}\n"
        f"- Hook hint: {concept.get('hook_hint')}\n"
        f"- Source type: {concept.get('source_type')}\n\n"
        "Write a standalone Short (NOT a summary of a long video).\n"
        "Structure: HOOK → CONTEXT → ESCALATION → PAYOFF → optional CTA.\n"
        f"Target {cfg.min_duration}-{cfg.max_duration}s (~{min_words}-{max_words} words).\n"
        "Script must be continuous spoken prose — connected sentences, no line-break pacing.\n"
        "The script field MUST begin with the exact hook text (copy hook verbatim as the opening).\n"
        "Ban: 'Hey guys', 'Welcome back', 'In today's video', generic AI filler, staccato one-liners.\n\n"
        "VISUAL SEGMENTS (critical — stock clips must match narration):\n"
        "- Split the script into 4-8 segments; each segment's `text` = the exact narration line it covers.\n"
        "- `keywords`: 2-4 concrete English words for Pexels video search (filmed objects/scenes).\n"
        "  GOOD: ['factory', 'assembly line'], ['hospital', 'MRI scanner'], ['laptop', 'typing closeup']\n"
        "  BAD: ['technology', 'abstract'], ['innovation', 'concept'], ['digital transformation']\n"
        "  Never use alone: technology, innovation, trends, futuristic, digital transformation.\n"
        "- `visual_intent`: one specific filmed scene (e.g. 'worker inspecting car engine').\n"
        "- Segments must follow script order; keywords must match what is being said in that line.\n\n"
        "JSON keys: title (max 70 chars, NO dashes or em-dashes like '-' or '—', NO colons ':'), hook, script, angle, key_claims (array), "
        "payoff, description, tags (array), hashtags (include #Shorts), "
        "visual_segments (array of {text, keywords, visual_intent, duration_hint as number in seconds}), "
        "target_duration_seconds, source_type, cta (optional)."
    )

    last_errors: list[str] = []
    max_attempts = 5
    for attempt in range(max_attempts):
        attempt_prompt = prompt
        if last_errors:
            attempt_prompt += (
                "\n\nPREVIOUS ATTEMPT FAILED VALIDATION — fix all of these:\n"
                + "\n".join(f"- {e}" for e in last_errors)
            )

        def _fetch(p=attempt_prompt):
            return chat(p, system=system, max_tokens=4096, json_mode=True)

        content = fetch_json_with_retries(
            _fetch,
            required_fields=SHORTS_CONTENT_FIELDS - {"cta"},
            log_prefix="[shorts/content]",
        )
        content.setdefault("source_type", concept.get("source_type", "evergreen"))
        content.setdefault("cta", "")
        content["hashtags"] = normalize_hashtags(content.get("hashtags"), default=["#Shorts"])
        content["description"] = fix_spaced_hashtags(content.get("description") or "")
        content = _ensure_script_starts_with_hook(content)
        content = refine_visual_segments(content)

        ok, errors = run_shorts_content_gate(content, concept, cfg)
        if ok:
            return content
        last_errors = errors
        print(
            f"[shorts/content] validation failed (attempt {attempt + 1}/{max_attempts}): "
            + "; ".join(errors),
            flush=True,
        )

    raise ValueError("; ".join(last_errors))
