import json
import os
import re
from datetime import datetime, timezone

from moduli.ai_client import chat_ollama
from moduli.preferenze import carica as carica_preferenze
from moduli.performance import (
    score_video,
    performance_snapshot_for_strategy,
    sync_profiles,
    detect_patterns,
    pattern_signals,
    carica_profili,
)

from moduli.strategy_memory import (
    load_history,
    save_history,
    record_strategy_cycle,
    memory_for_llm,
    memory_context_block,
)
from moduli.strategy_output import attach_structured_strategy, structured_summary_text
from moduli.analytics_learning import insights_for_llm

LEARNINGS_FILE = "video_learnings.json"
ANALYTICS_UNAVAILABLE_NOTE = "No reliable analytics yet -> standard strategy."

DEFAULT_STRATEGY = {
    "topic_focus": "AI and technology trends",
    "preferred_angle": "",
    "content_format": "",
    "title_style": "curiosity-driven, slightly provocative",
    "tone": "confident and informative",
    "hook_strength": "medium",
    "script_structure": "hook in first 15 seconds, then context, 3-4 key beats, strong close with CTA",
    "target_minutes": None,
    "pacing": "medium",
    "video_style": "cinematic documentary",
    "thumbnail_style": "",
    "avoid_patterns": "",
    "notes": "No prior data. Use standard approach.",
}

STRATEGY_PROMPT = """You are a long-term YouTube growth strategist for a tech/AI channel.

Recent video performance (newest first):
{performance_json}

Top performing videos (highest score):
{top_performers}

Underperforming videos (lowest score):
{underperformers}

Previous strategies tried (most recent first):
{history_json}

User preferences (HARD CONSTRAINTS — never violate):
{preferences}

Data-driven signals (computed from analytics — trust these numbers):
{analytics_insights}

Winning patterns (relative to YOUR channel — double down):
{winning_patterns}

Losing patterns (relative to YOUR channel — avoid):
{losing_patterns}

Accumulated strategy memory (historical successes AND failures — prefer high-confidence entries):
{strategy_memory}

Compact learning summary (channel-relative signals — trust over raw metrics):
{learning_summary}

Long-term channel memory:
{memoria_block}

Produce an EVOLVED strategy that:
- Learns from what's working and what isn't (CTR, retention, views)
- Identifies TOPIC PATTERNS from top vs bottom performers
- Avoids repeating failed title styles, tones, topic angles, thumbnail approaches
- Doubles down on patterns that increased CTR or retention
- Respects user preferences absolutely

Reply ONLY valid JSON:
{{
  "topic_focus": "specific topic areas/angles that showed best performance",
  "preferred_angle": "one creative angle to use for the next topic (e.g. contrarian take, case study)",
  "content_format": "one format: listicle | case study | explainer | news reaction | timeline | versus",
  "title_style": "concrete actionable title writing style based on what worked",
  "tone": "narration tone",
  "hook_strength": "soft | medium | aggressive",
  "script_structure": "how to structure the script (hook timing, sections, pacing)",
  "target_minutes": 8,
  "pacing": "slow | medium | fast",
  "video_style": "cinematic | fast cuts | minimal | documentary",
  "thumbnail_style": "visual style for thumbnail image generation based on CTR learnings",
  "avoid_patterns": "specific titles, tones, topics, angles to AVOID — be concrete",
  "notes": "3-5 data-backed lessons + concrete improvement plan for the NEXT video"
}}

Rules:
- Compare ONLY to this channel's history — never invent YouTube-wide benchmarks
- Avg CTR < 3%: bolder titles, stronger curiosity gap, aggressive hooks, bolder thumbnail_style
- Retention < 40%: harder opening hook, faster pacing, shorter intro, natural spoken flow (not staccato beats)
- High CTR + low retention: packaging overpromises — soften titles/thumbnails, deliver value earlier
- Low CTR + strong retention: improve packaging without dumbing down content
- Views < 100 on 3+ recent videos: pivot topic category, not just title tweaks
- If top performers share a topic pattern: pursue that direction with NEW subjects (never repeat topics)
- target_minutes: adjust from user pref if retention is strong (can go longer) or weak (shorten 1-2 min)
- With n<=2 videos: conservative strategy only — insufficient data for strong claims
- Reply ONLY with JSON, no explanation outside JSON.
"""


def _perf_snapshot(videos: list[dict]) -> list[dict]:
    """Vista compatta per LLM — preferisce profili arricchiti se presenti."""
    if videos and videos[0].get("performance_score") is not None:
        return performance_snapshot_for_strategy(videos)
    return [
        {
            "title": v.get("title", "")[:60],
            "views": v.get("views", 0),
            "ctr_pct": round(float(v.get("ctr_percent") or 0), 2),
            "retention_pct": round(
                float(v.get("retention_percent") or 0) or (
                    float(v.get("avg_view_duration_seconds") or 0) /
                    max(float(v.get("duration_seconds") or 1), 1.0) * 100
                ), 1
            ),
            "views_per_day": round(
                float(v.get("views") or 0) /
                max(float(v.get("age_hours") or 24) / 24.0, 0.25), 1
            ) if v.get("age_hours") else None,
            "performance_score": round(score_video(v), 1),
        }
        for v in videos
    ]


def _load_history() -> list:
    return load_history()


def _save_history(history: list) -> None:
    save_history(history)


def _legacy_history_slice(history: list, n: int = 5) -> list:
    """Compatibilità: vecchie entry hanno solo strategy/top/underperformers."""
    out = []
    for entry in history[-n:]:
        if entry.get("successful_topics") or entry.get("winning_patterns"):
            out.append({
                "date": entry.get("date"),
                "confidence_level": entry.get("confidence_level"),
                "videos_analyzed": entry.get("videos_analyzed"),
                "winning_patterns": entry.get("winning_patterns", [])[:4],
                "losing_patterns": entry.get("losing_patterns", [])[:4],
                "avoid_patterns": entry.get("avoid_patterns", ""),
                "strategy": entry.get("strategy", {}),
            })
        else:
            out.append(entry)
    return out


def _record_cycle(
    profiles: list[dict],
    insights: dict,
    strategy: dict,
    top: list[dict],
    bottom: list[dict],
) -> None:
    pattern_profiles = carica_profili() if profiles else []
    if not pattern_profiles:
        pattern_profiles = profiles
    record_strategy_cycle(pattern_profiles, insights, strategy, top, bottom)


def _load_learnings() -> list:
    if os.path.exists(LEARNINGS_FILE):
        try:
            with open(LEARNINGS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_learnings(learnings: list) -> None:
    with open(LEARNINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(learnings[-30:], f, indent=2, ensure_ascii=False)


def normalize_strategy(raw: dict | None) -> dict:
    """Merge con default e normalizza tipi per il resto della pipeline."""
    if not raw:
        return DEFAULT_STRATEGY.copy()
    out = {**DEFAULT_STRATEGY, **raw}
    notes = out.get("notes")
    if isinstance(notes, list):
        out["notes"] = "\n".join(str(n) for n in notes)
    tm = out.get("target_minutes")
    if tm is not None:
        try:
            out["target_minutes"] = max(1, min(30, int(tm)))
        except (TypeError, ValueError):
            out["target_minutes"] = None
    for key in ("avoid_patterns", "topic_focus", "title_style", "thumbnail_style",
                "preferred_angle", "content_format", "script_structure", "video_style"):
        if out.get(key) is None:
            out[key] = DEFAULT_STRATEGY.get(key, "")
        else:
            out[key] = str(out[key]).strip()
    pacing = str(out.get("pacing", "medium")).lower()
    if pacing not in ("slow", "medium", "fast", "lento", "medio", "veloce"):
        pacing = "medium"
    out["pacing"] = {"lento": "slow", "medio": "medium", "veloce": "fast"}.get(pacing, pacing)
    return out


def _metrics_row(video: dict) -> dict:
    """Appiattisce profilo persistente o riga analytics grezza."""
    if video.get("metrics"):
        m = video["metrics"]
        return {
            "views": m.get("views", 0),
            "ctr_percent": m.get("ctr_percent", 0),
            "avg_view_duration_seconds": m.get("avg_view_duration_seconds", 0),
            "duration_seconds": m.get("duration_seconds", 1),
            "retention_percent": m.get("retention_percent", 0),
            "title": video.get("title", ""),
            "performance_score": video.get("performance_score"),
        }
    return video


def analyze_performance(
    performance: list[dict],
    pref: dict | None = None,
    *,
    synced_profiles: list[dict] | None = None,
    state: dict | None = None,
) -> dict:
    """Analisi deterministica pre-LLM — segnali oggettivi per la strategia."""
    pref = pref or carica_preferenze()
    if not performance and not synced_profiles:
        return {
            "video_count": 0,
            "avg_ctr": 0.0,
            "avg_retention": 0.0,
            "avg_views": 0.0,
            "suggested_target_minutes": pref.get("durata_target_minuti", 8),
            "signals": ["No published videos yet — use user preferences as primary guide."],
            "winning_patterns": [],
            "losing_patterns": [],
            "by_tier": {t: [] for t in ("breakout", "strong", "average", "weak", "poor")},
        }

    # Pattern detection su tutto il canale (profili persistenti), non solo ultimo batch
    if synced_profiles is not None:
        pattern_source = synced_profiles
    else:
        all_profiles = carica_profili()
        pattern_source = all_profiles if len(all_profiles) >= len(performance) else performance
    patterns = detect_patterns(pattern_source)

    metrics_rows = performance
    if not metrics_rows and synced_profiles:
        from moduli.performance import profilo_to_analytics_row
        metrics_rows = [profilo_to_analytics_row(p) for p in synced_profiles]

    ctrs, retentions, views_list, scores = [], [], [], []
    for v in metrics_rows:
        row = _metrics_row(v)
        views_list.append(float(row.get("views") or 0))
        ctrs.append(float(row.get("ctr_percent") or 0))
        ret = float(row.get("retention_percent") or 0)
        if not ret:
            dur = max(float(row.get("duration_seconds") or 1), 1.0)
            ret = float(row.get("avg_view_duration_seconds") or 0) / dur * 100
        retentions.append(ret)
        if v.get("performance_score") is not None:
            scores.append(float(v["performance_score"]) * 100)

    avg_ctr = sum(ctrs) / len(ctrs)
    avg_ret = sum(retentions) / len(retentions)
    avg_views = sum(views_list) / len(views_list)
    base_minutes = int(pref.get("durata_target_minuti", 8))

    signals = []
    if avg_ctr < 3:
        signals.append(f"LOW CTR ({avg_ctr:.1f}%): strengthen titles, hooks, and thumbnail contrast.")
    elif avg_ctr >= 6:
        signals.append(f"STRONG CTR ({avg_ctr:.1f}%): keep title/thumbnail formula, iterate on topics.")

    if avg_ret < 40:
        signals.append(f"LOW RETENTION ({avg_ret:.0f}%): aggressive hook, faster pacing, shorter intro.")
        suggested = max(3, base_minutes - 2)
    elif avg_ret >= 55:
        signals.append(f"STRONG RETENTION ({avg_ret:.0f}%): audience tolerates longer content.")
        suggested = min(15, base_minutes + 1)
    else:
        suggested = base_minutes

    if avg_views < 100 and len(metrics_rows) >= 2:
        signals.append("LOW VIEWS: consider pivoting topic category, not just packaging.")

    top = max(metrics_rows, key=score_video) if metrics_rows else {}
    if top.get("title") or _metrics_row(top).get("title"):
        title = (top.get("title") or _metrics_row(top).get("title", ""))[:50]
        signals.append(f"Best performer: '{title}' (score {score_video(top):.0f}/100).")

    result = {
        "video_count": len(metrics_rows),
        "avg_ctr": round(avg_ctr, 2),
        "avg_retention": round(avg_ret, 1),
        "avg_views": round(avg_views, 0),
        "suggested_target_minutes": suggested,
        "signals": signals,
    }
    if scores:
        result["avg_performance_score"] = round(sum(scores) / len(scores), 1)

    result["winning_patterns"] = patterns.get("winning_patterns", [])
    result["losing_patterns"] = patterns.get("losing_patterns", [])
    result["by_tier"] = patterns.get("by_tier", {})
    result["channel_median_score"] = patterns.get("channel_median_score", 0)
    result["winners_count"] = patterns.get("winners_count", 0)
    result["losers_count"] = patterns.get("losers_count", 0)
    signals.extend(pattern_signals(patterns))

    try:
        from moduli.channel_confidence import confidence_dict, confidence_from_profiles
        conf = confidence_from_profiles(pattern_source)
        result["channel_confidence"] = confidence_dict(conf)
        signals.insert(
            0,
            f"CONFIDENCE {conf.level} ({conf.video_count} videos) — {conf.optimization_mode}",
        )
    except Exception:
        pass

    try:
        from moduli.publish_optimization import analyze_publish_timing, publish_guidance_text
        pub = analyze_publish_timing(pattern_source)
        result["publish_timing_analysis"] = pub
        if pub.get("sufficient_evidence") and pub.get("recommended_hours_utc"):
            signals.append(
                f"PUBLISH — recommended hours UTC: {pub['recommended_hours_utc'][:4]}"
            )
        elif pub.get("has_data"):
            signals.append("PUBLISH — insufficient evidence to change schedule")
        result["publish_guidance"] = publish_guidance_text(pattern_source)
    except Exception:
        pass

    try:
        from moduli.title_learning import analyze_title_patterns
        title_analysis = analyze_title_patterns(pattern_source)
        result["title_pattern_analysis"] = title_analysis
        for wp in (title_analysis.get("winning_title_patterns") or [])[:3]:
            signals.append(
                f"TITLE WIN — {wp['pattern_label']}: CTR {wp['avg_ctr']}% "
                f"({wp['ctr_vs_channel']:+.1f}), retention {wp['avg_retention']}% "
                f"({wp['retention_vs_channel']:+.1f}), velocity {wp['avg_velocity']}/day"
            )
        for lp in (title_analysis.get("losing_title_patterns") or [])[:2]:
            signals.append(
                f"TITLE LOSE — {lp['pattern_label']}: underperforms channel median "
                f"(score {lp['score_vs_channel']:+.1f} pts)"
            )
    except Exception:
        pass

    try:
        from moduli.hook_optimization import analyze_hook_patterns
        ha = analyze_hook_patterns(pattern_source)
        result["hook_pattern_analysis"] = ha
        for rec in (ha.get("strategy_recommendations") or [])[:2]:
            signals.append(f"HOOK — {rec}")
        for wp in (ha.get("winning_hook_patterns") or [])[:2]:
            detail = f"+{wp['retention_vs_channel']:.0f}% retention"
            if wp.get("retention_30s_vs_channel") is not None:
                detail = f"+{wp['retention_30s_vs_channel']:.0f}% at 30s"
            signals.append(f"HOOK WIN — {wp['hook_label']} ({detail})")
    except Exception:
        pass

    try:
        from moduli.script_optimization import analyze_script_optimization
        sa = analyze_script_optimization(pattern_source)
        result["script_optimization"] = sa
        if sa.get("sufficient_evidence"):
            for rec in (sa.get("recommendations") or [])[:2]:
                if rec.get("retention_vs_channel", 0) >= 3:
                    signals.append(
                        f"SCRIPT — {rec['dimension']}={rec['value']} "
                        f"(+{rec['retention_vs_channel']:.0f}% retention, n={rec['sample_size']})"
                    )
        elif sa.get("has_data"):
            signals.append("SCRIPT — insufficient data for script changes; keeping defaults")
    except Exception:
        pass

    try:
        from moduli.thumbnail_learning import analyze_thumbnail_patterns
        ta = analyze_thumbnail_patterns(pattern_source)
        result["thumbnail_pattern_analysis"] = ta
        if ta.get("sufficient_evidence"):
            for wt in (ta.get("winning_traits") or [])[:2]:
                signals.append(
                    f"THUMB WIN — {wt['dimension']}={wt['value']}: "
                    f"CTR {wt['avg_ctr']}% ({wt['ctr_vs_channel']:+.1f}, n={wt['sample_size']})"
                )
        elif ta.get("has_data"):
            signals.append("THUMBNAIL — insufficient data to claim winning styles")
    except Exception:
        pass

    try:
        from moduli.experimentation import experiment_stats, experimentation_guidance_text
        result["experimentation"] = experiment_stats()
        for line in experimentation_guidance_text().split("\n")[:4]:
            if line.strip():
                signals.append(f"EXPERIMENT — {line.strip()}")
    except Exception:
        pass

    try:
        from moduli.analytics import leggi_channel_audience_bundle
        from moduli.analytics_learning import enrich_insights_with_learning, persist_content_quality_lessons

        channel_bundle = None
        sched_cache = (state or {}).get("_scheduler_cache") or {}
        if sched_cache.get("audience_bundle"):
            channel_bundle = sched_cache["audience_bundle"]
        if not channel_bundle:
            channel_bundle = leggi_channel_audience_bundle()
        result = enrich_insights_with_learning(
            result, pattern_source, channel_bundle=channel_bundle,
        )
        persist_content_quality_lessons(result.get("learning_summary") or {})
    except Exception as e:
        print(f"[strategia] learning summary skip: {e}", flush=True)

    result["signals"] = result.get("signals") or signals
    return result


def _memoria_block() -> str:
    try:
        from moduli.memoria import come_contesto
        block = come_contesto()
        return block if block else "(none)"
    except Exception:
        return "(none)"


def _learnings_block() -> str:
    learnings = _load_learnings()[-5:]
    if not learnings:
        return "(none)"
    lines = []
    for entry in learnings:
        lines.append(
            f"- {entry.get('date', '?')}: '{entry.get('title', '')[:40]}' "
            f"(topic: {entry.get('topic', '')[:30]}) — strategy notes: "
            f"{str(entry.get('strategy_notes', ''))[:120]}"
        )
    return "\n".join(lines)


def registra_esito(
    video_id: str,
    topic: str,
    title: str,
    strategy: dict,
    content: dict | None = None,
    publish_time: str | None = None,
) -> None:
    """Collega video pubblicato a strategia + metadati pipeline."""
    from moduli.performance import registra_pubblicazione

    if content:
        registra_pubblicazione(video_id, topic, title, content, strategy, publish_time)
        try:
            from moduli.experimentation import record_video_classification
            exp = (content.get("_strategy_meta") or {}).get("experimentation") or {}
            if exp:
                record_video_classification(video_id, topic, title, exp)
        except Exception as e:
            print(f"[experimentation] record skip: {e}", flush=True)
    learnings = _load_learnings()
    learnings.append({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "video_id": video_id,
        "topic": topic,
        "title": title,
        "strategy_notes": strategy.get("notes", ""),
        "avoid_patterns": strategy.get("avoid_patterns", ""),
        "topic_focus": strategy.get("topic_focus", ""),
    })
    _save_learnings(learnings)


def _empty_insights(pref: dict | None = None, extra_signal: str = "") -> dict:
    pref = pref or carica_preferenze()
    signals = [ANALYTICS_UNAVAILABLE_NOTE]
    if extra_signal:
        signals.append(extra_signal)
    return {
        "video_count": 0,
        "avg_ctr": 0.0,
        "avg_retention": 0.0,
        "avg_views": 0.0,
        "suggested_target_minutes": pref.get("durata_target_minuti", 8),
        "signals": signals,
        "winning_patterns": [],
        "losing_patterns": [],
        "by_tier": {t: [] for t in ("breakout", "strong", "average", "weak", "poor")},
        "channel_confidence": {
            "level": "LOW",
            "video_count": 0,
            "optimization_mode": "standard",
        },
    }


def standard_strategy(
    pref: dict | None = None,
    *,
    reason: str | None = None,
    state: dict | None = None,
) -> dict:
    """Strategia di fallback quando analytics o strategy generation non sono affidabili."""
    pref = pref or carica_preferenze()
    note = (reason or ANALYTICS_UNAVAILABLE_NOTE).strip()
    strat = normalize_strategy({
        **DEFAULT_STRATEGY,
        "topic_focus": ", ".join(pref.get("argomenti_preferiti", [])) or DEFAULT_STRATEGY["topic_focus"],
        "thumbnail_style": pref.get("stile_thumbnail", ""),
        "video_style": pref.get("stile_clip", "cinematic"),
        "pacing": pref.get("ritmo", "medio"),
        "target_minutes": pref.get("durata_target_minuti", 8),
        "notes": note,
    })
    strat["_analytics_fallback"] = True
    insights = _empty_insights(pref)
    return attach_structured_strategy(strat, insights, state=state, profiles=[], pref=pref)


def calcola_strategia(performance: list[dict] | None = None, state: dict | None = None) -> dict:
    """Calcola strategia da analytics — non solleva mai: fallback su standard_strategy."""
    try:
        return _calcola_strategia_core(performance or [], state)
    except Exception as e:
        safe_note = ANALYTICS_UNAVAILABLE_NOTE.replace("\u2192", "->")
        print(
            f"[strategia] strategy fallback ({e}): {safe_note}",
            flush=True,
        )
        return standard_strategy(reason=ANALYTICS_UNAVAILABLE_NOTE)


def _calcola_strategia_core(performance: list[dict], state: dict | None = None) -> dict:
    pref = carica_preferenze()
    profiles: list[dict] = []
    if performance:
        try:
            profiles = sync_profiles(performance)
        except Exception as e:
            print(f"[strategia] sync_profiles skip: {e}", flush=True)
    try:
        insights = analyze_performance(
            profiles or performance, pref, synced_profiles=profiles or None, state=state,
        )
    except Exception as e:
        print(f"[strategia] analyze_performance skip: {e}", flush=True)
        insights = _empty_insights(pref, str(e))

    def _finalize(strat: dict) -> dict:
        strat["_winning_patterns"] = insights.get("winning_patterns", [])[:5]
        strat["_losing_patterns"] = insights.get("losing_patterns", [])[:5]
        strat["_by_tier"] = insights.get("by_tier", {})
        strat["_learning_summary"] = insights.get("learning_summary")
        strat["_insights"] = insights
        try:
            return attach_structured_strategy(
                strat, insights, state=state, profiles=profiles, pref=pref,
            )
        except Exception as e:
            print(f"[strategia] structured strategy skip: {e}", flush=True)
            strat.setdefault("structured", {})
            return strat

    if not performance:
        strat = normalize_strategy({
            **DEFAULT_STRATEGY,
            "topic_focus": ", ".join(pref.get("argomenti_preferiti", [])) or DEFAULT_STRATEGY["topic_focus"],
            "thumbnail_style": pref.get("stile_thumbnail", ""),
            "video_style": pref.get("stile_clip", "cinematic"),
            "pacing": pref.get("ritmo", "medio"),
            "target_minutes": insights["suggested_target_minutes"],
            "notes": ANALYTICS_UNAVAILABLE_NOTE,
        })
        return _finalize(strat)

    history = _load_history()
    ranked = profiles or performance
    scored = sorted(ranked, key=score_video, reverse=True)
    top = _perf_snapshot(scored[:3])
    bottom = _perf_snapshot(scored[-3:]) if len(scored) > 3 else []

    try:
        prompt = STRATEGY_PROMPT.format(
            performance_json=json.dumps(_perf_snapshot(ranked), indent=2),
            top_performers=json.dumps(top, indent=2),
            underperformers=json.dumps(bottom, indent=2),
            history_json=json.dumps(_legacy_history_slice(history), indent=2) if history else "[]",
            preferences=json.dumps(pref, indent=2, ensure_ascii=False),
            analytics_insights=json.dumps(insights_for_llm(insights), indent=2),
            winning_patterns=json.dumps(insights.get("winning_patterns", []), indent=2),
            losing_patterns=json.dumps(insights.get("losing_patterns", []), indent=2),
            strategy_memory=json.dumps(memory_for_llm(), indent=2),
            learning_summary=(insights.get("learning_summary") or {}).get("text_block", "(none)"),
            memoria_block=_memoria_block() + "\n\n" + memory_context_block(),
        )
        from moduli.ai_validation import fetch_json_with_retries
        strategy_data = fetch_json_with_retries(
            lambda: chat_ollama(prompt, max_tokens=1200, json_mode=True),
            required_fields=set(),
            max_attempts=3,
            log_prefix="[strategia]",
        )
        strategy = normalize_strategy(strategy_data)
        if strategy.get("target_minutes") is None:
            strategy["target_minutes"] = insights["suggested_target_minutes"]
        if not strategy.get("thumbnail_style"):
            strategy["thumbnail_style"] = pref.get("stile_thumbnail", "")
        _record_cycle(profiles, insights, strategy, top, bottom)
        print(
            f"[strategia] CTR medio {insights['avg_ctr']}% | "
            f"retention {insights['avg_retention']}% | "
            f"target {strategy['target_minutes']} min",
            flush=True,
        )
        return _finalize(strategy)
    except Exception as e:
        print(f"Strategy generation failed: {e}. Using analytics fallback.", flush=True)

    # fallback deterministico se LLM fallisce
    losing = insights.get("losing_patterns") or []
    winning = insights.get("winning_patterns") or []
    avoid_bits = [lp.get("pattern", "") for lp in losing[:4]]
    if not avoid_bits:
        avoid_bits = ["Generic AI explainer titles, weak hooks, low-contrast thumbnails"]
    win_note = winning[0]["pattern"] if winning else ""
    notes_parts = list(insights.get("signals", []))
    if win_note:
        notes_parts.insert(0, f"Double down: {win_note}")
    fallback = normalize_strategy({
        **DEFAULT_STRATEGY,
        "topic_focus": top[0].get("topic") or top[0].get("title", "")[:80] if top else DEFAULT_STRATEGY["topic_focus"],
        "hook_strength": "aggressive" if insights["avg_ctr"] < 3 else "medium",
        "pacing": "fast" if insights["avg_retention"] < 40 else pref.get("ritmo", "medium"),
        "target_minutes": insights["suggested_target_minutes"],
        "thumbnail_style": pref.get("stile_thumbnail", ""),
        "video_style": pref.get("stile_clip", "cinematic"),
        "avoid_patterns": "; ".join(avoid_bits),
        "notes": "; ".join(notes_parts),
    })
    _record_cycle(profiles, insights, fallback, top, bottom)
    return _finalize(fallback)


def storia_strategia() -> list:
    return load_history()


def strategia_memory() -> dict:
    return memory_for_llm()


def video_learnings() -> list:
    return _load_learnings()
