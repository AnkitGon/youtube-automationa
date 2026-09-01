"""
Storia permanente dei topic — vietato ripetere lo stesso argomento (anche semanticamente).

Ogni topic ha un'identità normalizzata (entità, soggetto, evento) — non solo il titolo.
topic_history.json è la fonte di verità; il confronto usa identity_hash e campi strutturati.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from moduli.topic_quality import try_topic_quality

TOPIC_HISTORY_FILE = "topic_history.json"
MAX_HISTORY_ENTRIES = 500
MAX_TOPIC_ATTEMPTS = 5
MAX_CATEGORY_RETRIES = 3
DEFAULT_SIMILARITY_THRESHOLD = 0.82
LLM_BORDERLINE_MARGIN = 0.12

STATUS_PUBLISHED = "published"
STATUS_RESERVED = "reserved"
STATUS_REJECTED_DUPLICATE = "rejected_duplicate"

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "as", "is", "was", "are", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must",
    "shall", "can", "how", "why", "what", "when", "where", "who", "which", "that", "this",
    "these", "those", "it", "its", "into", "about", "over", "under", "after", "before",
    "than", "then", "there", "their", "they", "them", "you", "your", "we", "our", "us",
    "he", "she", "his", "her", "not", "no", "yes", "all", "any", "each", "every", "both",
    "few", "more", "most", "other", "some", "such", "only", "own", "same", "so", "too",
    "very", "just", "also", "now", "new", "old", "one", "two", "three", "first", "last",
    "real", "reason", "story", "explained", "explain", "truth", "behind", "inside", "war",
})

_FAILURE_TOKENS = frozenset({
    "fail", "failed", "failure", "failing", "flop", "flopped", "lost", "lose", "losing",
    "died", "death", "dead", "collapse", "collapsed", "fall", "fell", "fallen", "killed",
    "kill", "bankrupt", "bankruptcy", "shutdown", "shut", "disaster", "downfall",
})

_RISE_TOKENS = frozenset({
    "rise", "rose", "risen", "grew", "growth", "boom", "surge", "dominate", "dominated",
    "won", "win", "winning", "success", "successful", "triumph",
})

_SUBJECT_MAP = (
    (r"\bsmartphone", "smartphone market"),
    (r"\bmobile phone", "mobile phone market"),
    (r"\bstreaming", "streaming industry"),
    (r"\bchip\b|\bsemiconductor|\bcpu\b|\bgpu\b", "semiconductor industry"),
    (r"\bai\b|\bartificial intelligence|\bllm\b|\bgpt\b", "artificial intelligence"),
    (r"\brobot", "robotics"),
    (r"\bstartup|\bstart-up", "startup ecosystem"),
    (r"\bsocial media", "social media"),
    (r"\belectric vehicle|\bev\b|\btesla\b", "electric vehicles"),
    (r"\bcloud\b", "cloud computing"),
)

_CATEGORY_RULES = (
    (r"\bfail|\bcollapse|\bbankrupt|\blost\b|\bdied\b|\bflop\b", "technology business failure"),
    (r"\bfuture\b|\bwill\b|\b2030\b|\bnext decade", "future prediction"),
    (r"\bvs\b|\bversus\b|\bcompared\b|\bbattle\b|\bwar\b", "comparison analysis"),
    (r"\bhow to\b|\btutorial|\bguide\b", "how-to tutorial"),
    (r"\bnews\b|\bannounced\b|\brelease\b", "tech news"),
)


class TopicDuplicateError(ValueError):
    """Topic semanticamente duplicato rispetto alla storia del canale."""

    def __init__(self, candidate: str, matched: str, reason: str = "", *, score: float | None = None):
        self.candidate = candidate
        self.matched = matched
        self.reason = reason
        self.score = score
        super().__init__(
            f"Topic duplicato: '{candidate}' ≈ '{matched}'"
            + (f" (score {score:.2f})" if score is not None else "")
            + (f" ({reason})" if reason else "")
        )


def similarity_threshold() -> float:
    """Soglia duplicato configurabile via TOPIC_SIMILARITY_THRESHOLD (default 0.82)."""
    raw = os.environ.get("TOPIC_SIMILARITY_THRESHOLD", str(DEFAULT_SIMILARITY_THRESHOLD))
    try:
        return max(0.5, min(0.99, float(raw)))
    except ValueError:
        return DEFAULT_SIMILARITY_THRESHOLD


def _llm_dedup_mode() -> str:
    """off | borderline (default) | always"""
    raw = os.environ.get("TOPIC_DEDUP_LLM", "borderline").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return "off"
    if raw in ("1", "true", "yes", "borderline"):
        return "borderline"
    if raw == "always":
        return "always"
    return "borderline"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _load_raw() -> dict:
    data = {}
    if os.path.exists(TOPIC_HISTORY_FILE):
        try:
            with open(TOPIC_HISTORY_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    if isinstance(data, list):
        return {"topics": data, "version": 2}
    if not isinstance(data, dict):
        return {"topics": [], "version": 2}
    data.setdefault("topics", [])
    data.setdefault("version", 2)
    return data


def _save_raw(data: dict) -> None:
    topics = [_normalize_registry_entry(e) for e in (data.get("topics") or [])]
    data["topics"] = topics[-MAX_HISTORY_ENTRIES:]
    data["version"] = 2
    data["updated_at"] = _now()
    with open(TOPIC_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_topic_history() -> list[dict]:
    """Carica il registro permanente topic (normalizzato)."""
    entries = [_normalize_registry_entry(e) for e in (_load_raw().get("topics") or [])]
    return entries


def load_topic_registry(*, status: str | None = None) -> list[dict]:
    """Registro topic con filtro opzionale per status (published, rejected_duplicate, ...)."""
    entries = load_topic_history()
    if status:
        return [e for e in entries if e.get("status") == status]
    return entries


def _normalize_registry_entry(entry: dict) -> dict:
    """Garantisce campi registro canonici su entry legacy o nuove."""
    if not isinstance(entry, dict):
        return {}
    ident = entry.get("identity") or {}
    topic = (entry.get("topic") or entry.get("original_topic") or ident.get("original_topic") or "").strip()
    normalized = (
        entry.get("normalized")
        or entry.get("normalized_topic")
        or ident.get("normalized_topic")
        or _normalize_phrase(topic)
    )
    entities = entry.get("entities")
    if not entities and ident.get("entities"):
        entities = ident.get("entities")
    category = entry.get("category") or entry.get("topic_category") or ident.get("topic_category") or ""
    status = entry.get("status") or STATUS_PUBLISHED
    date = entry.get("date") or entry.get("recorded_at") or _now()
    out = {
        **entry,
        "topic": topic,
        "normalized": normalized,
        "date": date,
        "video_id": entry.get("video_id"),
        "title": entry.get("title") or topic,
        "category": category,
        "entities": list(entities or []),
        "status": status,
        # legacy aliases
        "original_topic": entry.get("original_topic") or topic,
        "normalized_topic": entry.get("normalized_topic") or normalized,
        "recorded_at": entry.get("recorded_at") or date,
    }
    if ident:
        out["identity"] = ident
    return out


def _registry_entry(
    topic: str,
    *,
    title: str | None = None,
    video_id: str | None = None,
    identity: dict | None = None,
    status: str = STATUS_PUBLISHED,
    source: str = "pipeline",
    rejection_reason: str | None = None,
    matched_topic: str | None = None,
) -> dict:
    """Voce canonica del registro permanente topic."""
    identity = identity or build_topic_identity(topic, title=title)
    now = _now()
    entry = {
        "topic": topic,
        "normalized": identity.get("normalized_topic") or _normalize_phrase(topic),
        "date": now,
        "video_id": video_id,
        "title": (title or topic)[:200],
        "category": identity.get("topic_category") or "",
        "entities": list(identity.get("entities") or []),
        "status": status,
        "source": source,
        "recorded_at": now,
        "original_topic": topic,
        "identity": identity,
        "normalized_topic": identity.get("normalized_topic"),
        "core_entity": identity.get("core_entity"),
        "identity_hash": identity.get("identity_hash"),
    }
    if rejection_reason:
        entry["rejection_reason"] = rejection_reason[:300]
    if matched_topic:
        entry["matched_topic"] = matched_topic[:200]
    return entry


def _normalize_phrase(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())).strip()


_ENTITY_SKIP = frozenset({
    "How", "Why", "What", "When", "Where", "Who", "The", "A", "An", "This", "That",
    "Real", "Fall", "Lost", "Failed", "Died", "Killed", "Story", "Reason", "Inside",
    "Next", "New", "Top", "Best", "Ultimate", "Complete", "Secret", "Hidden", "True",
})


_KNOWN_BRANDS = (
    "OpenAI", "ChatGPT", "YouTube", "GitHub", "TikTok", "iPhone", "Android",
    "Microsoft", "Google", "Amazon", "Netflix", "Blockbuster", "Nokia", "Apple",
    "Tesla", "Meta", "Facebook", "Instagram", "GPT", "CUDA", "Intel", "AMD",
)


def _extract_entities(text: str) -> list[str]:
    """Estrae company/person/product — ignora parole interrogative e verbi nel titolo."""
    candidates: list[str] = []
    for brand in _KNOWN_BRANDS:
        if re.search(rf"\b{re.escape(brand)}\b", text or "", re.I):
            candidates.append(brand if brand != "iPhone" else "iPhone")
    for m in re.finditer(r"\b([A-Z][a-z]+)\b", text or ""):
        w = m.group(1)
        if w in _ENTITY_SKIP or w.lower() in _STOPWORDS:
            continue
        candidates.append(w)
    for m in re.finditer(r"\b([A-Z]{2,6})\b", text or ""):
        tok = m.group(1)
        if tok not in ("THE", "AND", "FOR", "WHY", "HOW", "GPT", "AI", "EV"):
            candidates.append(tok)
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        key = c.lower()
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out[:6]


def _infer_subject(text: str) -> str:
    t = (text or "").lower()
    for pattern, label in _SUBJECT_MAP:
        if re.search(pattern, t):
            return label
    return ""


def _infer_event(text: str) -> str:
    t = (text or "").lower()
    if any(re.search(rf"\b{re.escape(w)}\b", t) for w in _FAILURE_TOKENS):
        if "smartphone" in t or "phone" in t:
            return "loss of smartphone leadership"
        if "market" in t or "industry" in t:
            return "market collapse"
        return "business failure"
    if any(re.search(rf"\b{re.escape(w)}\b", t) for w in _RISE_TOKENS):
        return "business success"
    if re.search(r"\bwar\b|\bvs\b|\bversus\b|\bbattle\b", t):
        return "competitive battle"
    if re.search(r"\bfuture\b|\bwill\b|\bpredict", t):
        return "future outlook"
    return "general analysis"


def _infer_category(text: str, event: str) -> str:
    t = (text or "").lower()
    for pattern, label in _CATEGORY_RULES:
        if re.search(pattern, t):
            return label
    if "failure" in event or "collapse" in event or "loss" in event:
        return "technology business failure"
    return "technology analysis"


def _build_normalized_topic(core_entity: str, subject: str, core_event: str) -> str:
    parts = [p.lower().strip() for p in (core_entity, subject, core_event) if p]
    return " ".join(parts) if parts else ""


def _compute_identity_hash(
    core_entity: str,
    subject: str,
    core_event: str,
    topic_category: str,
) -> str:
    payload = "|".join(
        _normalize_phrase(p)
        for p in (core_entity, subject, core_event, topic_category)
        if p
    )
    if not payload:
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _llm_extract_identity(text: str) -> dict | None:
    if os.environ.get("TOPIC_IDENTITY_LLM", "0").strip().lower() in ("0", "false", "no"):
        return None
    try:
        from moduli.ai_client import chat_ollama
        prompt = f"""Extract structured topic identity for YouTube deduplication.

TEXT:
"{text}"

Reply ONLY JSON:
{{
  "normalized_topic": "short canonical label e.g. Nokia smartphone business failure",
  "entities": ["Nokia"],
  "core_entity": "primary company/person/product",
  "subject": "market or domain e.g. smartphone market",
  "core_event": "core story arc e.g. loss of smartphone leadership",
  "topic_category": "e.g. technology business failure",
  "core_claim": "one sentence core claim"
}}"""
        from moduli.ai_validation import parse_json_object, AIResponseError
        raw = chat_ollama(prompt, max_tokens=300, json_mode=True)
        data = parse_json_object(raw, {"normalized_topic"})
        if isinstance(data, dict):
            return data
    except AIResponseError as e:
        print(f"[topic_history] LLM identity invalid: {e}", flush=True)
    except Exception as e:
        print(f"[topic_history] LLM identity skip: {e}", flush=True)
    return None


def build_topic_identity(text: str, *, title: str | None = None) -> dict:
    """
    Costruisce identità topic normalizzata — non basata solo sul titolo.
    Usa euristica; arricchisce con LLM se TOPIC_IDENTITY_LLM=1.
    """
    original = (text or "").strip()
    combined = f"{original}. {title}" if title and title.strip() != original.strip() else original

    llm = _llm_extract_identity(combined)
    if llm:
        entities = llm.get("entities") or []
        if isinstance(entities, str):
            entities = [entities]
        core_entity = (llm.get("core_entity") or (entities[0] if entities else "")).strip()
        subject = (llm.get("subject") or "").strip()
        core_event = (llm.get("core_event") or "").strip()
        topic_category = (llm.get("topic_category") or "").strip()
        normalized = (llm.get("normalized_topic") or "").strip()
        if not normalized:
            normalized = _build_normalized_topic(core_entity, subject, core_event)
        identity = {
            "original_topic": original,
            "normalized_topic": normalized,
            "entities": entities,
            "core_entity": core_entity,
            "subject": subject,
            "core_event": core_event,
            "topic_category": topic_category or _infer_category(combined, core_event),
            "core_claim": (llm.get("core_claim") or normalized or original)[:300],
        }
        identity["identity_hash"] = _compute_identity_hash(
            identity["core_entity"], identity["subject"],
            identity["core_event"], identity["topic_category"],
        )
        return identity

    entities = _extract_entities(combined)
    core_entity = entities[0] if entities else ""
    subject = _infer_subject(combined)
    core_event = _infer_event(combined)
    topic_category = _infer_category(combined, core_event)
    normalized = _build_normalized_topic(core_entity, subject, core_event)
    if not normalized:
        normalized = _normalize_phrase(original)

    core_claim = original
    if core_entity and core_event:
        core_claim = f"{core_entity}: {core_event}"
        if subject:
            core_claim = f"{core_entity} / {subject}: {core_event}"

    identity = {
        "original_topic": original,
        "normalized_topic": normalized,
        "entities": entities,
        "core_entity": core_entity,
        "subject": subject,
        "core_event": core_event,
        "topic_category": topic_category,
        "core_claim": core_claim[:300],
    }
    identity["identity_hash"] = _compute_identity_hash(
        core_entity, subject, core_event, topic_category,
    )
    return identity


def _events_compatible(a: str, b: str) -> bool:
    """Stesso arco narrativo (es. entrambi fallimenti)."""
    fa = any(w in (a or "").lower() for w in ("fail", "collapse", "loss", "death", "downfall"))
    fb = any(w in (b or "").lower() for w in ("fail", "collapse", "loss", "death", "downfall"))
    if fa and fb:
        return True
    ra = any(w in (a or "").lower() for w in ("success", "rise", "growth", "dominat"))
    rb = any(w in (b or "").lower() for w in ("success", "rise", "growth", "dominat"))
    if ra and rb:
        return True
    if _normalize_phrase(a) == _normalize_phrase(b):
        return True
    return False


def _subjects_compatible(a: str, b: str) -> bool:
    if not a or not b:
        return True
    na, nb = _normalize_phrase(a), _normalize_phrase(b)
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    ta, tb = _canonical_tokens(a), _canonical_tokens(b)
    return bool(ta & tb)


def _canonical_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if word in _STOPWORDS or len(word) < 2:
            continue
        if word in _FAILURE_TOKENS:
            tokens.add("__failure__")
            continue
        if word.endswith("ies") and len(word) > 4:
            tokens.add(word[:-3] + "y")
        elif word.endswith("s") and len(word) > 3 and not word.endswith("ss"):
            tokens.add(word[:-1])
        else:
            tokens.add(word)
    return tokens


def _heuristic_similarity(a: str, b: str) -> float:
    ta, tb = _canonical_tokens(a), _canonical_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    if union == 0:
        return 0.0
    score = inter / union
    shared_long = {t for t in ta & tb if len(t) >= 4 and not t.startswith("__")}
    if shared_long and ("__failure__" in ta and "__failure__" in tb):
        score = max(score, 0.55 + min(0.35, len(shared_long) * 0.12))
    elif len(shared_long) >= 2:
        score = max(score, 0.45 + min(0.25, len(shared_long) * 0.08))
    return min(score, 1.0)


def _fuzzy_similarity(a: str, b: str) -> float:
    na, nb = _normalize_phrase(a), _normalize_phrase(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _entity_overlap_score(a: dict, b: dict) -> float:
    ea = {e.lower() for e in (a.get("entities") or []) if e}
    eb = {e.lower() for e in (b.get("entities") or []) if e}
    for key in ("core_entity",):
        for ident, bucket in ((a, ea), (b, eb)):
            val = _normalize_phrase(ident.get(key, ""))
            if val:
                bucket.add(val)
    if not ea or not eb:
        return 0.0
    return len(ea & eb) / len(ea | eb)


def compute_similarity(candidate: dict, stored: dict) -> dict:
    """
    Score composito 0–1 senza LLM:
      - identity match
      - entity overlap
      - token jaccard (normalized)
      - fuzzy similarity (rewording detection)
    """
    identity = identity_match_score(candidate, stored)
    entity_ov = _entity_overlap_score(candidate, stored)
    norm_a = candidate.get("normalized_topic") or candidate.get("original_topic", "")
    norm_b = stored.get("normalized_topic") or stored.get("original_topic", "")
    orig_a = candidate.get("original_topic", "")
    orig_b = stored.get("original_topic", "")
    token_sim = _heuristic_similarity(norm_a, norm_b)
    fuzzy_norm = _fuzzy_similarity(norm_a, norm_b)
    fuzzy_orig = _fuzzy_similarity(orig_a, orig_b)

    # rewording: stesse entità + testo simile ma non identico
    rewording = (
        entity_ov >= 0.5 and max(fuzzy_orig, fuzzy_norm, token_sim) >= 0.62
    ) or identity >= 0.88

    blended = (
        identity * 0.40
        + entity_ov * 0.25
        + token_sim * 0.20
        + max(fuzzy_norm, fuzzy_orig) * 0.15
    )
    combined = max(identity, blended)
    if rewording and entity_ov >= 0.33:
        combined = max(combined, 0.86)
    if entity_ov >= 0.66 and _events_compatible(
        candidate.get("core_event", ""), stored.get("core_event", "")
    ):
        combined = max(combined, 0.84)

    return {
        "combined": round(min(combined, 1.0), 4),
        "identity": round(identity, 4),
        "entity_overlap": round(entity_ov, 4),
        "token_similarity": round(token_sim, 4),
        "fuzzy_normalized": round(fuzzy_norm, 4),
        "fuzzy_original": round(fuzzy_orig, 4),
        "rewording": rewording,
    }


def _best_similarity_match(
    candidate_id: dict,
    stored: list[tuple[dict, str]],
) -> tuple[float, str | None, dict]:
    best_score = 0.0
    best_label: str | None = None
    best_detail: dict = {}
    for ident, label in stored:
        detail = compute_similarity(candidate_id, ident)
        if detail["combined"] > best_score:
            best_score = detail["combined"]
            best_label = label
            best_detail = detail
    return best_score, best_label, best_detail


def _should_llm_confirm(combined: float, threshold: float) -> bool:
    mode = _llm_dedup_mode()
    if mode == "off":
        return False
    if mode == "always":
        return combined >= threshold - 0.25
    return threshold - LLM_BORDERLINE_MARGIN <= combined < threshold


def identity_match_score(candidate: dict, stored: dict) -> float:
    """Score 0–1: quanto l'identità candidata coincide con una già registrata."""
    if not candidate or not stored:
        return 0.0

    h1 = candidate.get("identity_hash") or ""
    h2 = stored.get("identity_hash") or ""
    if h1 and h2 and h1 == h2:
        return 1.0

    ce1 = _normalize_phrase(candidate.get("core_entity", ""))
    ce2 = _normalize_phrase(stored.get("core_entity", ""))
    if ce1 and ce2 and ce1 == ce2:
        sub_ok = _subjects_compatible(candidate.get("subject", ""), stored.get("subject", ""))
        evt_ok = _events_compatible(candidate.get("core_event", ""), stored.get("core_event", ""))
        if sub_ok and evt_ok:
            return 0.95
        if evt_ok and (sub_ok or not candidate.get("subject") or not stored.get("subject")):
            return 0.88

    norm_sim = _heuristic_similarity(
        candidate.get("normalized_topic", ""),
        stored.get("normalized_topic", ""),
    )
    if norm_sim >= 0.72:
        return norm_sim

    text_sim = _heuristic_similarity(
        candidate.get("original_topic", ""),
        stored.get("original_topic", ""),
    )
    return max(norm_sim, text_sim * 0.9)


def _entry_identity(entry: dict) -> dict:
    if entry.get("identity"):
        return entry["identity"]
    topic = entry.get("original_topic") or entry.get("topic") or ""
    return build_topic_identity(topic, title=entry.get("title"))


def _all_stored_identities() -> list[tuple[dict, str]]:
    """(identity, display_label) per ogni entry in storia."""
    out: list[tuple[dict, str]] = []
    for entry in load_topic_history():
        ident = _entry_identity(entry)
        label = (
            entry.get("original_topic")
            or entry.get("topic")
            or ident.get("normalized_topic")
            or "?"
        )
        out.append((ident, str(label)))
    return out


def _all_history_texts() -> list[str]:
    texts: list[str] = []
    seen: set[str] = set()
    for entry in load_topic_history():
        for key in ("original_topic", "topic", "title", "normalized_topic"):
            val = (entry.get(key) or (entry.get("identity") or {}).get(key.replace("topic", "original_topic"), "")).strip()
            if key == "normalized_topic" and not val:
                val = (entry.get("identity") or {}).get("normalized_topic", "")
            norm = _normalize_phrase(val)
            if val and norm not in seen:
                seen.add(norm)
                texts.append(val)
    return texts


def _exact_duplicate(candidate: str, others: list[str] | None) -> str | None:
    norm_c = _normalize_phrase(candidate)
    for raw in others or []:
        val = (raw or "").strip()
        if val and _normalize_phrase(val) == norm_c:
            return val
    return None


def _migrate_external_sources() -> None:
    data = _load_raw()
    topics = data.get("topics") or []
    existing_hash = {
        (e.get("identity") or {}).get("identity_hash")
        for e in topics
        if (e.get("identity") or {}).get("identity_hash")
    }

    added = 0
    try:
        from moduli.performance import carica_profili
        for p in carica_profili():
            val = (p.get("topic") or p.get("title") or "").strip()
            if not val:
                continue
            ident = build_topic_identity(val, title=p.get("title"))
            if ident.get("identity_hash") in existing_hash:
                continue
            topics.append(_normalize_registry_entry({
                "original_topic": val,
                "topic": val,
                "title": p.get("title", ""),
                "video_id": p.get("video_id"),
                "date": p.get("published_at") or _now(),
                "recorded_at": p.get("published_at") or _now(),
                "status": STATUS_PUBLISHED,
                "source": "migrated_profile",
                "identity": ident,
                "normalized": ident.get("normalized_topic"),
                "normalized_topic": ident.get("normalized_topic"),
                "category": ident.get("topic_category"),
                "entities": ident.get("entities") or [],
                "core_entity": ident.get("core_entity"),
                "identity_hash": ident.get("identity_hash"),
            }))
            existing_hash.add(ident.get("identity_hash"))
            added += 1
    except Exception:
        pass

    if added:
        data["topics"] = topics
        _save_raw(data)


def _llm_duplicate_judge(candidate: str, prior_texts: list[str]) -> tuple[bool, str | None, str]:
    if not prior_texts:
        return False, None, ""
    try:
        from moduli.ai_client import chat_ollama
        from moduli.ai_validation import parse_json_object, AIResponseError
    except Exception:
        return False, None, ""

    history_block = "\n".join(f"- {t}" for t in prior_texts[:40])
    prompt = f"""You are a strict topic deduplication judge for a YouTube channel.

NEW TOPIC:
"{candidate}"

ALREADY USED TOPICS (never repeat the same underlying story):
{history_block}

Is the NEW TOPIC semantically the SAME underlying video topic as ANY item above?
Same company/person/product + same story arc = DUPLICATE even if wording differs.

Reply ONLY JSON:
{{"duplicate": true or false, "matches": "exact previous topic text or null", "reason": "brief"}}"""

    try:
        raw = chat_ollama(prompt, max_tokens=200, json_mode=True)
        data = parse_json_object(raw, {"duplicate"})
        if data.get("duplicate"):
            return True, data.get("matches") or prior_texts[0], data.get("reason", "")
    except AIResponseError as e:
        print(f"[topic_history] LLM dedup invalid: {e}", flush=True)
    except Exception as e:
        print(f"[topic_history] LLM dedup skip: {e}", flush=True)
    return False, None, ""


def find_semantic_duplicate(
    candidate: str,
    *,
    title: str | None = None,
    queue_peers: list[str] | None = None,
    use_llm: bool | None = None,
) -> tuple[bool, str | None, str]:
    """
    Pipeline deduplicazione:
      1. normalizza → identità
      2. confronta tutta la storia
      3. entity overlap + token + fuzzy + identity (senza LLM)
      4. LLM opzionale solo in zona borderline (non esclusivo)
    """
    candidate = (candidate or "").strip()
    if not candidate:
        return False, None, ""

    exact = _exact_duplicate(candidate, queue_peers)
    if exact:
        return True, exact, "already in queue"

    threshold = similarity_threshold()
    candidate_id = build_topic_identity(candidate, title=title)
    stored = _all_stored_identities()
    if not stored:
        return False, None, ""

    norm_c = _normalize_phrase(candidate)
    for _ident, label in stored:
        if _normalize_phrase(label) == norm_c:
            return True, label, "exact normalized match"

    best_score, best_label, detail = _best_similarity_match(candidate_id, stored)

    if best_score >= threshold:
        reason = _format_dup_reason(detail, best_score)
        return True, best_label, reason

    if use_llm is None:
        use_llm = _llm_dedup_mode() != "off"

    if use_llm and best_label and _should_llm_confirm(best_score, threshold):
        close_labels = [
            label for ident, label in stored
            if compute_similarity(candidate_id, ident)["combined"] >= threshold - LLM_BORDERLINE_MARGIN
        ][:12]
        dup, match, reason = _llm_duplicate_judge(candidate, close_labels or [best_label])
        if dup:
            return True, match or best_label, reason or "llm borderline confirm"

    return False, None, ""


def _format_dup_reason(detail: dict, score: float) -> str:
    parts = [f"similarity {score:.2f}"]
    if detail.get("rewording"):
        parts.append("rewording")
    if detail.get("entity_overlap", 0) >= 0.5:
        parts.append(f"entity_overlap {detail['entity_overlap']:.2f}")
    if detail.get("identity", 0) >= 0.85:
        parts.append(f"identity {detail['identity']:.2f}")
    return ", ".join(parts)


def assert_unique_topic(
    candidate: str,
    *,
    title: str | None = None,
    queue_peers: list[str] | None = None,
    use_llm: bool | None = None,
) -> str:
    candidate = (candidate or "").strip().strip('"“”‘’\' ')
    if not candidate:
        raise TopicDuplicateError("", "", "empty topic")
    dup, matched, reason = find_semantic_duplicate(
        candidate, title=title, queue_peers=queue_peers, use_llm=use_llm,
    )
    if dup:
        score = 0.0
        if matched:
            cand_id = build_topic_identity(candidate, title=title)
            for ident, label in _all_stored_identities():
                if label == matched:
                    score = compute_similarity(cand_id, ident)["combined"]
                    break
        raise TopicDuplicateError(candidate, matched or "?", reason, score=score or None)
    return candidate


def _find_registered_entry(topic: str, identity: dict | None = None) -> dict | None:
    """Trova entry registro già presente per topic/identità."""
    identity = identity or build_topic_identity(topic)
    norm = _normalize_phrase(topic)
    for entry in load_topic_history():
        if _normalize_phrase(entry.get("topic") or "") == norm:
            return entry
        existing = _entry_identity(entry)
        if compute_similarity(identity, existing)["combined"] >= similarity_threshold():
            return entry
    return None


def reserve_topic(
    topic: str,
    *,
    source: str = "manual",
    queue_peers: list[str] | None = None,
) -> dict:
    """
    Registra un topic manuale/coda come usato subito (status=reserved).
    Blocca duplicati semantici futuri prima della pubblicazione.
    """
    topic = (topic or "").strip().strip('"“”‘’\' ')
    if not topic:
        raise ValueError("empty topic")

    ok, cleaned, err = try_topic_quality(topic)
    if not ok:
        raise ValueError(err or "topic quality failed")
    topic = cleaned

    norm = _normalize_phrase(topic)
    for entry in load_topic_history():
        if _normalize_phrase(entry.get("topic") or "") == norm:
            if entry.get("status") in (STATUS_PUBLISHED, STATUS_RESERVED):
                return entry
            break

    dup, matched, reason = find_semantic_duplicate(
        topic, queue_peers=queue_peers, use_llm=False,
    )
    if dup:
        record_rejected_topic(topic, matched=matched, reason=reason or "duplicate")
        raise TopicDuplicateError(topic, matched or "?", reason)

    identity = build_topic_identity(topic)
    data = _load_raw()
    topics = [_normalize_registry_entry(e) for e in (data.get("topics") or [])]
    entry = _registry_entry(
        topic,
        identity=identity,
        status=STATUS_RESERVED,
        source=source,
    )
    topics.append(entry)
    data["topics"] = topics
    _save_raw(data)
    return entry


def ensure_queue_topics_reserved(state: dict | None = None) -> int:
    """Migra topic già in coda verso il registro permanente (reserved)."""
    state = state or {}
    reserved_n = 0
    queue = [t.strip() for t in (state.get("topic_queue") or []) if (t or "").strip()]
    for i, topic in enumerate(queue):
        peers = [t for j, t in enumerate(queue) if j != i]
        if _find_registered_entry(topic):
            continue
        try:
            reserve_topic(topic, source="queue", queue_peers=peers)
            reserved_n += 1
        except (TopicDuplicateError, ValueError):
            continue
    return reserved_n


def record_topic(
    topic: str,
    *,
    title: str | None = None,
    video_id: str | None = None,
    source: str = "pipeline",
) -> dict:
    """Registra topic usato/pubblicato nel registro permanente."""
    topic = (topic or "").strip()
    if not topic:
        return {}

    identity = build_topic_identity(topic, title=title)
    data = _load_raw()
    topics = [_normalize_registry_entry(e) for e in (data.get("topics") or [])]

    for entry in topics:
        existing = _entry_identity(entry)
        if compute_similarity(identity, existing)["combined"] >= similarity_threshold():
            entry["identity"] = identity
            entry["normalized"] = identity.get("normalized_topic")
            entry["normalized_topic"] = identity.get("normalized_topic")
            entry["category"] = identity.get("topic_category") or entry.get("category", "")
            entry["entities"] = list(identity.get("entities") or [])
            entry["core_entity"] = identity.get("core_entity")
            entry["identity_hash"] = identity.get("identity_hash")
            if video_id or entry.get("status") == STATUS_RESERVED:
                entry["status"] = STATUS_PUBLISHED
            entry["date"] = _now()
            entry["recorded_at"] = entry["date"]
            if video_id:
                entry["video_id"] = video_id
            if title:
                entry["title"] = title
            data["topics"] = topics
            _save_raw(data)
            return entry

    entry = _registry_entry(
        topic,
        title=title,
        video_id=video_id,
        identity=identity,
        status=STATUS_PUBLISHED,
        source=source,
    )
    topics.append(entry)
    data["topics"] = topics
    _save_raw(data)
    return entry


def record_rejected_topic(
    topic: str,
    *,
    matched: str | None = None,
    reason: str = "",
    status: str = STATUS_REJECTED_DUPLICATE,
    source: str = "generation",
) -> dict:
    """
    Registra topic rifiutato (es. duplicato) per non rigenerarlo.
    Persiste su topic_history.json — sopravvive ai riavvii del daemon.
    """
    topic = (topic or "").strip()
    if not topic:
        return {}

    identity = build_topic_identity(topic, title=matched)
    data = _load_raw()
    topics = [_normalize_registry_entry(e) for e in (data.get("topics") or [])]
    norm_new = identity.get("normalized_topic") or _normalize_phrase(topic)

    for entry in topics:
        if entry.get("status") != status:
            continue
        norm_old = entry.get("normalized") or entry.get("normalized_topic") or ""
        if _normalize_phrase(norm_old) == _normalize_phrase(norm_new):
            entry["date"] = _now()
            entry["recorded_at"] = entry["date"]
            if reason:
                entry["rejection_reason"] = reason[:300]
            if matched:
                entry["matched_topic"] = matched[:200]
            data["topics"] = topics
            _save_raw(data)
            return entry

    entry = _registry_entry(
        topic,
        identity=identity,
        status=status,
        source=source,
        rejection_reason=reason,
        matched_topic=matched,
    )
    topics.append(entry)
    data["topics"] = topics
    _save_raw(data)
    return entry


def banned_topics_block(max_items: int = 60) -> str:
    entries = load_topic_history()
    if not entries:
        return "(none yet)"
    lines: list[str] = []
    for entry in entries[-max_items:]:
        ident = entry.get("identity") or {}
        orig = entry.get("original_topic") or entry.get("topic") or "?"
        norm = ident.get("normalized_topic") or entry.get("normalized_topic") or ""
        if norm and norm != _normalize_phrase(orig):
            lines.append(f"- {orig} → [{norm}]")
        else:
            lines.append(f"- {orig}")
    if len(entries) > max_items:
        lines.append(f"... and {len(entries) - max_items} more (all permanently banned)")
    return "\n".join(lines)


def registry_stats() -> dict:
    """Conteggi registro topic per dashboard Telegram."""
    entries = load_topic_history()
    published = sum(1 for e in entries if e.get("status") == STATUS_PUBLISHED)
    reserved = sum(1 for e in entries if e.get("status") == STATUS_RESERVED)
    rejected = sum(1 for e in entries if e.get("status") == STATUS_REJECTED_DUPLICATE)
    return {
        "total": len(entries),
        "published": published,
        "reserved": reserved,
        "rejected_duplicate": rejected,
        "historical": published + reserved,
    }


def try_reserve_topic(
    candidate: str,
    queue_peers: list[str] | None = None,
) -> tuple[bool, str]:
    """API per Telegram/coda: qualità + dedup + registrazione immediata (reserved)."""
    try:
        reserve_topic(candidate, source="manual", queue_peers=queue_peers)
        return True, ""
    except TopicDuplicateError as e:
        return False, str(e)
    except ValueError as e:
        return False, f"Qualità topic insufficiente: {e}"


def seed_from_state(state: dict) -> None:
    for t in state.get("recent_topics") or []:
        if (t or "").strip():
            record_topic(t.strip(), source="migrated_state")


def used_subject_labels() -> set[str]:
    """Soggetti/categorie già coperti — per forzare cambio categoria in generazione."""
    labels: set[str] = set()
    for entry in load_topic_history():
        ident = _entry_identity(entry)
        for key in ("subject", "topic_category", "normalized_topic", "core_entity"):
            val = (ident.get(key) or entry.get(key) or "").strip().lower()
            if val:
                labels.add(val)
    return labels


def ensure_topic_history_seeded(state: dict | None = None) -> None:
    if not load_topic_history():
        _migrate_external_sources()
    if state:
        seed_from_state(state)
        ensure_queue_topics_reserved(state)
    elif load_topic_history():
        return
    else:
        _migrate_external_sources()
