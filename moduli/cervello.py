
import json
import random
import re
from datetime import datetime

from moduli.ai_client import chat_ollama

# Pool di "leve" creative: ad ogni run ne peschiamo una a caso per spingere il
# modello fuori dal solito titolo/argomento. Senza questo l'LLM converge sempre
# sullo stesso tema (es. "il futuro dell'AI") e sullo stesso titolo.
_ANGLES = [
    "a surprising real-world consequence",
    "a contrarian take most people get wrong",
    "a hidden risk nobody talks about",
    "a behind-the-scenes look at how it actually works",
    "a head-to-head comparison",
    "a beginner-friendly explainer of a complex idea",
    "a near-future prediction with concrete stakes",
    "a myth-busting deep dive",
    "an underrated tool or technique",
    "a story of a spectacular failure and its lesson",
    "a practical how-to people can use today",
    "a 'what if' thought experiment",
]
_FORMATS = [
    "listicle (top N)",
    "single big idea explained",
    "case study",
    "tutorial / walkthrough",
    "news reaction / analysis",
    "myth vs reality",
    "timeline / evolution story",
    "versus comparison",
]
_SUBTHEMES = [
    "AI models and capabilities",
    "AI tools for creators and productivity",
    "robotics and automation",
    "AI ethics, safety and regulation",
    "AI in everyday consumer tech",
    "the business and money behind AI",
    "AI hardware and chips",
    "open-source vs closed AI",
    "AI and jobs / the future of work",
    "breakthrough research and science",
]

TOPIC_PROMPT = """You are a viral YouTube content strategist for a tech/AI channel.

=== CONTEXT ===
Today's date: {current_date}

=== CURRENT STRATEGY ===
{strategy_block}

=== WINNING PATTERNS (repeat these categories/formats — but with a NEW subject) ===
{winning_block}

=== LOSING PATTERNS (do NOT imitate these) ===
{losing_block}

=== AVOID PATTERNS (MANDATORY) ===
{avoid_block}

=== CURRENT TRENDS (timely inspiration only — do not copy headlines verbatim) ===
{trending_block}

=== EXPLORATION / EXPLOITATION GUIDANCE ===
{diversity_block}

=== ANALYTICS LEARNING (channel-relative — do not ignore) ===
{analytics_learning_block}

Creative levers for this attempt:
- Sub-theme: {subtheme}
- Creative angle: {angle}
- Content format: {fmt}

=== CHANNEL TOPIC HISTORY (already published — permanently banned) ===
Every topic below has been covered on this channel. You must NOT reuse the same underlying story, entity, or narrative arc — even with different wording:
{historical_topics}

Also avoid these recent pipeline topics: {recent_topics}

=== REJECTED THIS SESSION (failed programmatic duplicate check) ===
{rejected_block}

=== YOUR TASK ===
Generate a topic that has NEVER been covered before on this channel and is NOT semantically similar to any historical topic listed above.
This must be a genuinely NEW subject: a different company, entity, event, story arc, and core claim.
Do NOT rephrase, remix, or narrow an existing historical topic.
Do NOT output a variation of anything in the rejected list.
Do NOT simply pick "another AI topic" — pick a specific, concrete, novel story.

{category_reuse_rule}

Output rules:
- Exactly 3-12 words
- A concrete subject (specific company, product, person, event, or story)
- NO explanations, reasoning, markdown, or JSON — topic phrase ONLY

Reply with ONLY the topic phrase. No explanation, no punctuation."""

CONTENT_PROMPT = """You are an expert documentary narrator for a tech/business YouTube channel.
Today's date: {current_date}
Create a complete video about: {topic}

{research_block}

{writing_rules_block}

{narrative_structure_block}

Strategy guidance:
- Title style: {title_style}
{title_guidance_block}
{hook_guidance_block}
{script_guidance_block}
{subscriber_guidance_block}
- Tone: {tone}
- Hook strength: {hook_strength}
- Script structure: {script_structure}
- Pacing: {pacing}
- Video style: {video_style}
- Notes: {strategy_notes}
{analytics_learning_block}
{avoid_block}

VIEWER VALUE (mandatory):
- Answer: what does the viewer KNOW or UNDERSTAND after watching that they did not before?
- Deliver concrete facts, context, WHY things happened, consequences, and memorable insights.
- Do NOT merely introduce a topic, repeat headlines, or create curiosity without payoff.
- The ending must provide a satisfying takeaway — not a generic subscribe plea.

Target duration: {target_minutes} minutes = ~{target_words} words
Language: write title, description, tags and script entirely in {language}.

Reply ONLY with valid JSON, exact structure:
{{
  "title": "Compelling title, max 70 chars, NO dashes (-) or em-dashes (—), NO colons (:)",
  "mood": "ONE word: epic | chill | mysterious | upbeat | tense",
  "thumbnail_phrase": "2-3 words MAX, ALL CAPS — complementary to title, NOT a repeat of title words",
  "thumbnail_font_size": "ONE letter: A | B | C | D",
  "description": "SEO description, 200-300 words",
  "tags": ["tag1", "tag2"],
  "script": "Full narration. Natural, intelligent, conversational human voice. Exactly {target_words} words. Flowing spoken prose — connected sentences, no headers, no line-break pacing.",
  "video_keywords": ["specific visual search phrase", "..."],
  "visual_segments": [
    {{"text_excerpt": "first ~40 words of narration this visual covers", "keyword": "specific stock footage search phrase", "visual_type": "stock|chart|archival|product"}}
  ],
  "thumbnail_description": "Image prompt for thumbnail. 80-120 words. NO text in image."
}}

{thumbnail_guidance_block}

Rules:
- title: follow title_style; NEVER use AVOID patterns; must be fulfilled by the script
- thumbnail_phrase: complements title (e.g. title 'How Nokia Lost the War' + thumbnail 'TOO LATE')
- script OPENING: follow hook_guidance_block — no slow generic setup if retention data says viewers drop early
- Choose narrative structure appropriate to topic — do not force identical template every video
- video_keywords: 12-18 English phrases, SPECIFIC to this story (not generic AI robots unless discussing AI)
- visual_segments: 8-15 segments aligned to script beats; keywords must match what is being SAID
- Do NOT invent statistics, quotes, dates, or events — use research brief or well-known public facts
- Mark uncertainty in narration when facts are disputed
"""

WRITING_RULES_BLOCK = """HUMAN WRITING RULES (avoid AI-sounding scripts):
- Write for SPOKEN delivery — the script will be read by TTS; it must sound natural aloud
- Vary sentence length and structure naturally; connect ideas with and/but/because/so
- NO staccato stacks of ultra-short sentences (they create dead-air gaps in TTS)
- NO: "In today's rapidly evolving world", excessive rhetorical questions, "But here's the thing",
  "Imagine...", fake excitement, robotic transitions, "Let's dive in", repetitive summaries
- YES: confident opinions when evidence supports them; uncertainty when facts are uncertain
- One natural CTA near the end at most — never desperate subscribe begging
- Write like a knowledgeable creator explaining to another person — not a Wikipedia article"""

NARRATIVE_STRUCTURES = (
    "story → conflict → turning point → lesson",
    "problem → explanation → solution",
    "timeline → causes → consequences",
    "mystery → investigation → reveal",
    "claim → evidence → counterpoint → conclusion",
    "comparison → evidence → verdict",
    "case study → failure → lesson",
)


def _strategy_block(strategy: dict) -> str:
    """Blocco strategia corrente per il prompt topic."""
    lines: list[str] = []
    for key, label in (
        ("topic_focus", "Topic focus"),
        ("preferred_angle", "Preferred angle"),
        ("content_format", "Content format"),
        ("title_style", "Title style"),
        ("hook_strength", "Hook strength"),
        ("target_minutes", "Target duration (min)"),
        ("pacing", "Pacing"),
        ("video_style", "Video style"),
        ("tone", "Tone"),
        ("avoid_patterns", "Avoid patterns"),
    ):
        val = strategy.get(key)
        if val is not None and str(val).strip():
            lines.append(f"- {label}: {str(val).strip()[:200]}")
    notes = strategy.get("notes", "")
    if isinstance(notes, list):
        notes = "; ".join(str(n) for n in notes)
    if notes and str(notes).strip():
        lines.append(f"- Notes: {str(notes).strip()[:500]}")
    return "\n".join(lines) if lines else "- Standard tech/AI channel approach"


def _pattern_lines(patterns: list, label_key: str = "pattern") -> list[str]:
    lines: list[str] = []
    for p in patterns or []:
        if not isinstance(p, dict):
            val = str(p).strip()
            if val:
                lines.append(f"- {val[:120]}")
            continue
        pat = (p.get(label_key) or p.get("value") or "").strip()
        if not pat:
            continue
        vs = p.get("vs_channel_median")
        suffix = f" ({vs:+g} pts vs channel median)" if vs is not None else ""
        lines.append(f"- [category/format] {pat[:120]}{suffix}")
    return lines


def _winning_patterns_block(strategy: dict) -> str:
    lines = _pattern_lines(strategy.get("_winning_patterns") or [])
    try:
        from moduli.strategy_memory import memory_for_llm
        mem = memory_for_llm()
        for item in (mem.get("historical_winning_patterns") or [])[:4]:
            if isinstance(item, dict):
                pat = (item.get("pattern") or item.get("value") or "").strip()
            else:
                pat = str(item).strip()
            if pat and f"- [category/format] {pat[:120]}" not in lines:
                lines.append(f"- [category/format] {pat[:120]} (historical)")
        for fmt in (mem.get("successful_formats") or [])[:2]:
            val = fmt.get("value") if isinstance(fmt, dict) else str(fmt)
            if val and val.strip():
                lines.append(f"- Successful format: {val.strip()[:80]}")
    except Exception:
        pass
    if not lines:
        return "- (no winning patterns yet — stay on-brand for tech/AI)"
    return "\n".join(dict.fromkeys(lines))


def _losing_patterns_block(strategy: dict, pref: dict) -> str:
    lines = _pattern_lines(strategy.get("_losing_patterns") or [])
    evitare = pref.get("argomenti_evitare") or []
    if evitare:
        lines.append(f"- User banned subjects: {', '.join(str(e) for e in evitare[:8])}")
    recent_avoid = strategy.get("_recent_underperformers") or []
    if recent_avoid:
        lines.append(
            "- Underperforming titles to NOT imitate: "
            + ", ".join(str(t) for t in recent_avoid[:5])
        )
    try:
        from moduli.strategy_memory import memory_for_llm
        mem = memory_for_llm()
        for item in (mem.get("historical_losing_patterns") or [])[:4]:
            if isinstance(item, dict):
                pat = (item.get("pattern") or item.get("value") or "").strip()
            else:
                pat = str(item).strip()
            if pat:
                lines.append(f"- {pat[:120]} (historical failure)")
    except Exception:
        pass
    if not lines:
        return "- (none identified)"
    return "\n".join(dict.fromkeys(lines))


def _avoid_block(strategy: dict, pref: dict) -> str:
    from moduli.avoid_patterns import avoid_block_for_content
    return avoid_block_for_content(strategy, pref)


def _topic_avoid_block(strategy: dict, pref: dict) -> str:
    from moduli.avoid_patterns import avoid_prompt_section
    block = avoid_prompt_section(strategy, pref, stage="topic")
    return block or "- (none — follow losing patterns and channel history)"


def _rejected_topics_block(
    rejected: list[str],
    force_category: bool = False,
    subtheme: str = "",
) -> str:
    lines: list[str] = []
    for topic in rejected[-8:]:
        if topic and topic.strip():
            lines.append(f"- {topic.strip()}")
    if force_category and subtheme:
        lines.append(
            f"- MANDATORY category shift: explore sub-theme «{subtheme}» "
            "(must not overlap any historical entity or story arc)"
        )
    if not lines:
        return "- (none this session)"
    return "\n".join(lines)


def build_topic_prompt(
    *,
    strategy: dict,
    pref: dict,
    recent_topics: list | None,
    rejected: list[str],
    trending_block: str,
    diversity_block: str,
    subtheme: str,
    angle: str,
    fmt: str,
    historical_topics: str,
    force_category: bool = False,
) -> str:
    """Assembla il prompt topic con tutte le sezioni richieste."""
    from moduli.channel_confidence import confidence_prompt_block
    from moduli.channel_learning import category_reuse_reminder
    try:
        from moduli.performance import carica_profili
        confidence_line = confidence_prompt_block(profiles=carica_profili())
    except Exception:
        confidence_line = confidence_prompt_block(video_count=0)
    try:
        from moduli.analytics_learning import learning_block_for_prompt
        analytics_learning = learning_block_for_prompt(strategy)
    except Exception:
        analytics_learning = "(no analytics learning yet)"
    trending = (trending_block or "").strip()
    if not trending:
        trending = "- (no live trend feed — use what's relevant as of today's date)"
    return TOPIC_PROMPT.format(
        current_date=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        strategy_block=confidence_line + "\n" + _strategy_block(strategy),
        winning_block=_winning_patterns_block(strategy),
        losing_block=_losing_patterns_block(strategy, pref),
        trending_block=trending,
        diversity_block=diversity_block,
        analytics_learning_block=analytics_learning,
        subtheme=subtheme,
        angle=angle,
        fmt=fmt,
        historical_topics=historical_topics,
        recent_topics=", ".join(recent_topics or []) or "none",
        rejected_block=_rejected_topics_block(rejected, force_category, subtheme),
        avoid_block=_topic_avoid_block(strategy, pref),
        category_reuse_rule=category_reuse_reminder(),
    )


def _pick_levers(strategy: dict) -> tuple[str, str, str]:
    """Sceglie angolo/formato/tema — strategia analytics prima, random come fallback."""
    angle = (strategy.get("preferred_angle") or "").strip()
    fmt = (strategy.get("content_format") or "").strip()
    focus = (strategy.get("topic_focus") or "").strip()

    if not angle:
        angle = random.choice(_ANGLES)
    if not fmt:
        fmt = random.choice(_FORMATS)

    # subtheme: prima parola chiave dal topic_focus, altrimenti random
    if focus and len(focus) > 10:
        subtheme = focus[:120]
    else:
        subtheme = random.choice(_SUBTHEMES)

    return angle, fmt, subtheme


def _pick_exploit_levers(strategy: dict) -> tuple[str, str, str]:
    """Leve allineate a pattern vincenti — nuovo soggetto, stessa categoria."""
    from moduli.topic_diversity import map_winning_pattern_to_levers
    angle, fmt, subtheme = map_winning_pattern_to_levers(strategy, _ANGLES, _FORMATS)
    if not subtheme:
        subtheme = random.choice(_SUBTHEMES)
    return angle, fmt, subtheme


def _pick_alternate_subtheme(strategy: dict, used_subjects: set, rejected: list) -> tuple[str, str, str]:
    """Dopo 5 tentativi falliti: forza subtheme lontano dalla storia del canale."""
    scored = []
    for s in _SUBTHEMES:
        sl = s.lower()
        overlap = sum(1 for u in used_subjects if u and (u in sl or sl in u))
        scored.append((overlap, s))
    scored.sort(key=lambda x: x[0])
    min_overlap = scored[0][0] if scored else 0
    pool = [s for o, s in scored if o == min_overlap] or list(_SUBTHEMES)
    subtheme = random.choice(pool[:4] if len(pool) > 4 else pool)
    return random.choice(_ANGLES), random.choice(_FORMATS), subtheme


def _target_minutes(strategy: dict, pref: dict) -> int:
    tm = strategy.get("target_minutes")
    if tm is not None:
        try:
            return max(1, min(30, int(tm)))
        except (TypeError, ValueError):
            pass
    return int(pref.get("durata_target_minuti", 8))


def _parse_json(text: str) -> dict:
    from moduli.ai_validation import parse_content_json, AIResponseError
    try:
        return parse_content_json(text)
    except AIResponseError as e:
        raise ValueError(str(e)) from e


def _fetch_trending(strategy: dict | None = None, subtheme: str = "") -> str:
    try:
        from moduli.research import fetch_trending_block
        return fetch_trending_block(strategy, subtheme)
    except Exception:
        pass
    return ""


def _writing_rules_block() -> str:
    from moduli.narration_quality import narration_prompt_block
    return WRITING_RULES_BLOCK + "\n\n" + narration_prompt_block("longform")


def _narrative_structure_block(strategy: dict) -> str:
    chosen = (strategy.get("script_structure") or "").strip()
    if chosen and len(chosen) > 15:
        return f"NARRATIVE STRUCTURE for this video:\n{chosen}\n"
    import random
    structure = random.choice(NARRATIVE_STRUCTURES)
    return (
        f"NARRATIVE STRUCTURE (pick and follow one arc — vary across videos):\n"
        f"Use: {structure}\n"
        f"Other options: {', '.join(NARRATIVE_STRUCTURES[:4])}\n"
    )


def genera_topic(strategy: dict = None, recent_topics: list = None, extra_banned: list = None) -> str:
    from moduli.topic_history import (
        assert_unique_topic,
        banned_topics_block,
        TopicDuplicateError,
        ensure_topic_history_seeded,
        record_rejected_topic,
        STATUS_REJECTED_DUPLICATE,
        MAX_TOPIC_ATTEMPTS,
        MAX_CATEGORY_RETRIES,
        used_subject_labels,
    )
    from moduli.topic_diversity import (
        decide_mode,
        diversity_prompt_block,
        record_mode,
        exploit_ratio,
    )
    from moduli.topic_quality import assert_topic_quality, TopicQualityError
    from moduli.avoid_patterns import assert_not_avoided, AvoidPatternError
    from moduli.research import infer_topic_source

    ensure_topic_history_seeded()
    strategy = strategy or {}
    try:
        from moduli.preferenze import carica
        pref = carica()
    except Exception:
        pref = {}

    banned_extra = list(extra_banned or [])
    rejected: list[str] = []
    used_subjects = used_subject_labels()
    total_attempts = MAX_TOPIC_ATTEMPTS + MAX_CATEGORY_RETRIES
    diversity_mode = decide_mode(strategy)
    initial_diversity_mode = diversity_mode

    def _clean(t: str) -> str:
        return t.strip().strip('"“”‘’\' ')

    for attempt in range(1, total_attempts + 1):
        force_category = attempt > MAX_TOPIC_ATTEMPTS
        if force_category:
            angle, fmt, subtheme = _pick_alternate_subtheme(strategy, used_subjects, rejected)
        elif diversity_mode == "exploit" and attempt == 1:
            angle, fmt, subtheme = _pick_exploit_levers(strategy)
        elif attempt > 1:
            angle, fmt, subtheme = _pick_levers({**strategy, "preferred_angle": "", "content_format": ""})
        elif diversity_mode == "explore":
            angle, fmt, subtheme = _pick_alternate_subtheme(strategy, used_subjects, rejected)
            strategy["_explore_subtheme"] = subtheme
        else:
            angle, fmt, subtheme = _pick_levers(strategy)

        trending = _fetch_trending(strategy, subtheme)

        phase = f"{diversity_mode}" + ("+cambio-cat" if force_category else "")
        print(
            f"[cervello] Topic mode={diversity_mode} ({phase}, {attempt}/{total_attempts}, "
            f"target exploit {int(exploit_ratio()*100)}%) — "
            f"tema:{subtheme[:40]} | angolo:{angle[:40]} | formato:{fmt}",
            flush=True,
        )
        prompt = build_topic_prompt(
            strategy=strategy,
            pref=pref,
            recent_topics=recent_topics,
            rejected=rejected,
            trending_block=trending,
            diversity_block=diversity_prompt_block(diversity_mode, strategy, subtheme),
            subtheme=subtheme,
            angle=angle,
            fmt=fmt,
            historical_topics=banned_topics_block(),
            force_category=force_category,
        )
        topic_raw = chat_ollama(prompt, max_tokens=256)
        try:
            from moduli.ai_validation import clean_topic_response, AIResponseError
            topic = _clean(clean_topic_response(topic_raw))
        except AIResponseError as e:
            rejected.append(topic_raw[:80] or "(vuoto)")
            print(
                f"[cervello] Topic risposta AI rifiutata — {e.reason} — ritento",
                flush=True,
            )
            continue
        if not topic:
            continue
        try:
            topic = assert_topic_quality(topic)
        except TopicQualityError as e:
            rejected.append(e.candidate or "(vuoto)")
            print(
                f"[cervello] Topic qualità rifiutato '{e.candidate}' — {e.reason} — ritento",
                flush=True,
            )
            continue
        try:
            assert_not_avoided(topic, "topic", strategy, pref)
        except AvoidPatternError as e:
            rejected.append(topic)
            print(
                f"[cervello] Topic avoid pattern '{e.pattern}' — ritento",
                flush=True,
            )
            continue
        # Validazione programmatica obbligatoria — mai accettare senza dedup semantico
        try:
            accepted = assert_unique_topic(topic, queue_peers=banned_extra or None)
            strategy["_topic_diversity_mode"] = initial_diversity_mode
            strategy["_topic_source"] = infer_topic_source(
                strategy,
                diversity_mode=initial_diversity_mode,
                from_trending=bool(trending.strip()),
            )
            record_mode(initial_diversity_mode, accepted)
            return accepted
        except TopicDuplicateError as e:
            rejected.append(topic)
            record_rejected_topic(
                topic,
                matched=e.matched,
                reason=e.reason or "duplicate",
                status=STATUS_REJECTED_DUPLICATE,
                source="topic_generation",
            )
            print(
                f"[cervello] Topic duplicato rifiutato '{topic}' ~ '{e.matched}' "
                f"({e.reason}) — ritento",
                flush=True,
            )

    raise RuntimeError(
        f"Impossibile generare un topic unico dopo {total_attempts} tentativi "
        f"({MAX_TOPIC_ATTEMPTS} standard + {MAX_CATEGORY_RETRIES} cambio categoria). "
        f"Ultimi rifiutati: {rejected[-3:]}"
    )


def genera_contenuto(topic: str, strategy: dict = None) -> dict:
    from moduli.topic_history import assert_unique_topic, TopicDuplicateError
    from moduli.ai_validation import parse_content_json, AIResponseError
    from moduli.title_learning import title_guidance_block, record_generated_title, classify_title_pattern
    from moduli.hook_optimization import (
        hook_guidance_block,
        record_generated_hook,
        classify_hook_type,
        opening_excerpt,
    )
    from moduli.script_optimization import script_guidance_block, apply_script_suggestions
    from moduli.thumbnail_learning import thumbnail_guidance_block, classify_thumbnail_traits
    from moduli.research import infer_topic_source, build_research_brief
    from moduli.content_quality import run_content_quality_gate, quality_summary_for_log
    from moduli.subscriber_learning import subscriber_guidance_block
    from moduli.avoid_patterns import validate_content_fields

    strategy = strategy or {}
    try:
        from moduli.preferenze import carica
        pref = carica()
    except Exception:
        pref = {}
    research = build_research_brief(topic)
    # Analisi script prima del prompt — suggerimenti conservativi in strategy
    script_guidance = script_guidance_block(strategy, pref)
    strategy = apply_script_suggestions(strategy, pref)
    target_minutes = _target_minutes(strategy, pref)
    language = pref.get("lingua", "english") or "english"
    tone = strategy.get("tone") or pref.get("tono_voce", "confident")
    pacing = strategy.get("pacing") or pref.get("ritmo", "medium")
    hook_strength = strategy.get("hook_strength") or "medium"
    video_style = strategy.get("video_style") or pref.get("stile_clip", "cinematic")
    thumbnail_style = strategy.get("thumbnail_style") or pref.get("stile_thumbnail", "")
    thumb_guidance = thumbnail_guidance_block(strategy)
    try:
        from moduli.analytics_learning import learning_block_for_prompt
        analytics_learning = learning_block_for_prompt(strategy)
    except Exception:
        analytics_learning = ""
    prompt = CONTENT_PROMPT.format(
        current_date=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        topic=topic,
        research_block=research.get("prompt_block", ""),
        writing_rules_block=_writing_rules_block(),
        narrative_structure_block=_narrative_structure_block(strategy),
        title_style=strategy.get("title_style", "curiosity-driven"),
        title_guidance_block=title_guidance_block(strategy),
        hook_guidance_block=hook_guidance_block(strategy),
        script_guidance_block=script_guidance,
        subscriber_guidance_block=subscriber_guidance_block(strategy),
        tone=tone,
        hook_strength=hook_strength,
        script_structure=strategy.get("script_structure", "hook first, then context, key beats, CTA close"),
        pacing=pacing,
        video_style=video_style,
        strategy_notes=strategy.get("notes", "Standard approach"),
        analytics_learning_block=analytics_learning,
        avoid_block=_avoid_block(strategy, pref),
        target_minutes=target_minutes,
        target_words=int(target_minutes * 130),
        language=language,
        thumbnail_guidance_block=thumb_guidance,
    )
    min_words = max(150, int(target_minutes * 130 * 0.5))
    last_err = None
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            attempt_prompt = prompt
            if last_err:
                attempt_prompt += (
                    f"\n\nPREVIOUS ATTEMPT FAILED — fix this:\n{last_err}\n"
                    "Reply with complete JSON. Must include video_keywords (array of 12-18 "
                    "English stock-search phrases) and visual_segments."
                )
            max_tokens = min(16384, 8192 + attempt * 2048)
            raw = chat_ollama(attempt_prompt, max_tokens=max_tokens, json_mode=True)
            content = parse_content_json(raw, topic=topic)
            from moduli.content_quality import prepare_content_for_validation
            content = prepare_content_for_validation(content, topic=topic)
            title = (content.get("title") or "").strip()
            if title:
                try:
                    assert_unique_topic(title)
                except TopicDuplicateError as e:
                    raise ValueError(
                        f"Titolo duplicato semanticamente: '{title}' ~ '{e.matched}'"
                    ) from e
                record_generated_title(title, strategy)
            script = content.get("script") or ""
            if script:
                record_generated_hook(script, strategy)
            words = len(script.split())
            if words < min_words:
                raise ValueError(
                    f"Script troppo corto: {words} parole, minimo {min_words} "
                    f"per un video da ~{target_minutes} minuti"
                )
            avoid_errors = validate_content_fields(content, strategy, pref)
            if avoid_errors and attempt < max_attempts - 1:
                raise ValueError("; ".join(avoid_errors))
            if avoid_errors:
                print(
                    f"[cervello] Avoid-pattern warnings ignored on final attempt: "
                    f"{'; '.join(avoid_errors[:2])}",
                    flush=True,
                )
            q_ok, q_errors = run_content_quality_gate(
                content, topic, strategy, attempt=attempt, max_attempts=max_attempts,
            )
            if not q_ok:
                raise ValueError("Quality gate: " + "; ".join(q_errors[:4]))
            from moduli.narration_quality import narration_summary_for_log
            print(f"[cervello] {narration_summary_for_log(script, 'longform')}", flush=True)
            # visual_segments drive montage; fallback to video_keywords
            segments = content.get("visual_segments") or []
            if segments:
                seg_kws = [s.get("keyword") for s in segments if s.get("keyword")]
                if seg_kws:
                    content["video_keywords"] = list(dict.fromkeys(
                        seg_kws + (content.get("video_keywords") or [])
                    ))[:20]
            from moduli.script_optimization import extract_script_traits
            traits = extract_script_traits(script)
            traits["pacing"] = pacing
            traits["hook_strength"] = hook_strength
            content["_strategy_meta"] = {
                "target_minutes": target_minutes,
                "pacing": pacing,
                "video_style": video_style,
                "thumbnail_style": thumbnail_style,
                "title_pattern": classify_title_pattern(title) if title else "",
                "title_experiment": (strategy.get("_title_experiment") or {}),
                "hook_type": classify_hook_type(opening_excerpt(script)) if script else "",
                "hook_experiment": (strategy.get("_hook_experiment") or {}),
                "script_traits": traits,
                "thumbnail_traits": classify_thumbnail_traits(
                    content.get("thumbnail_description") or "",
                    content.get("thumbnail_phrase") or "",
                    content.get("mood") or "",
                ),
                "script_suggestions": strategy.get("_script_suggestions") or {},
                "topic_source": strategy.get("_topic_source") or infer_topic_source(strategy),
                "research_snippet_count": len(research.get("snippets") or []),
            }
            print(f"[cervello] {quality_summary_for_log(content, topic)}", flush=True)
            from moduli.hashtags import fix_spaced_hashtags
            content["description"] = fix_spaced_hashtags(content.get("description") or "")
            from moduli.experimentation import classify_video_strategy
            content["_strategy_meta"]["experimentation"] = classify_video_strategy(
                topic, strategy, content
            )
            return content
        except ValueError as e:
            last_err = e
            print(f"[cervello] Contenuto non valido (tentativo {attempt + 1}/{max_attempts}): {e}", flush=True)
        except AIResponseError as e:
            last_err = ValueError(str(e))
            print(f"[cervello] Contenuto non valido (tentativo {attempt + 1}/{max_attempts}): {e}", flush=True)
    raise last_err
