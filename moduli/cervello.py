
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

Today's date: {current_date}
Current strategy guidance: {strategy_notes}
Topic focus: {topic_focus}
{trending_block}
For THIS video, lean into:
- Sub-theme to explore: {subtheme}
- Creative angle: {angle}
- Content format: {fmt}

Generate ONE trending topic for a YouTube video about AI or technology.
Base your suggestion on what is relevant and trending as of {current_date}.
Use the trending news above as inspiration for a timely, high-interest angle — not a copy.
Make it clearly DIFFERENT from the recent topics below — new subject, new framing.
Avoid repeating these recent topics: {recent_topics}
Reply with ONLY the topic as a short phrase (3-7 words). No explanation, no punctuation."""

CONTENT_PROMPT = """You are a viral YouTube scriptwriter for a tech/AI channel.
Today's date: {current_date}
Create a complete video about: {topic}

Strategy guidance:
- Title style: {title_style}
- Tone: {tone}
- Hook strength: {hook_strength}
- Notes: {strategy_notes}

Target duration: {target_minutes} minutes = ~{target_words} words
Language: write title, description, tags and script entirely in {language}.

Reply ONLY with valid JSON, exact structure:
{{
  "title": "Compelling title, max 70 chars",
  "mood": "ONE word matching the video's emotional tone: epic | chill | mysterious | upbeat | tense",
  "thumbnail_phrase": "2-3 words MAX, ALL CAPS, bold visual hook for the thumbnail — never more than 3 words, never cut off",
  "thumbnail_font_size": "ONE letter: A (very large, best for 2 words), B (large, 2 words), C (medium, 2-3 words, default), D (smaller, 3 words)",
  "description": "SEO-optimized description, 200-300 words, include keywords naturally",
  "tags": ["tag1", "tag2", "tag3"],
  "script": "Full narration. Engaging, clear, conversational. Exactly {target_words} words. No headers or sections, flowing prose.",
  "video_keywords": [
    "AI neural network visualization",
    "futuristic city technology",
    "scientist working computer"
  ],
  "thumbnail_description": "Ultra-detailed image generation prompt for FLUX.1 diffusion model. Must be ONE paragraph, 80-120 words. Describe: exact scene composition, foreground subject with precise visual details (clothing, pose, expression, materials), background environment (architecture, lighting, atmosphere, depth), color palette (specific hues, contrast, saturation), lighting setup (direction, quality, color temperature, shadows), cinematic style, camera angle, lens feel. Professional YouTube thumbnail aesthetic, bold visual impact, 16:9 landscape orientation. NO text, logos, watermarks, or words of any kind — pure visual only. Example depth: 'Close-up photorealistic render of a humanoid robot with brushed titanium face and glowing cyan eye lenses, emerging from a dark server room filled with blue neon-lit racks, volumetric fog drifting at ankle level, dramatic rim lighting from the left casting sharp shadows, deep blacks and electric blue highlights, ultra-sharp detail, 85mm portrait lens perspective, cinematic anamorphic flare.'"
}}

Rules:
- title: follow the title_style guidance above
- mood: exactly one of epic, chill, mysterious, upbeat, tense — drives background music and thumbnail style
- thumbnail_phrase: EXACTLY 2-3 words, ALL CAPS, bold hook — never more than 3 words
- thumbnail_font_size: A if 2 short words, B if 2 longer words, C if 3 words (default), D if 3 long words
- tags: 12-15 relevant tags
- script: exactly {target_words} words, engaging pace, no bullet points
- video_keywords: 12-18 unique English phrases describing stock video scenes (2-4 words each, concrete and visual)
- thumbnail_description: ultra-detailed FLUX.1 prompt as described above, always present
"""


def _parse_json(text: str) -> dict:
    decoder = json.JSONDecoder()
    start = text.find("{")
    if start < 0:
        raise ValueError("No JSON found in model response")
    try:
        data, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError as e:
        snippet = text[:500].replace("\n", "\\n")
        raise ValueError(f"Invalid JSON from model: {e}; response starts with: {snippet}") from e
    required = {"title", "description", "tags", "script", "video_keywords"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Model JSON missing required fields: {', '.join(sorted(missing))}")
    return data


def _fetch_trending() -> str:
    try:
        from moduli.web_search import cerca_notizie
        results = cerca_notizie("AI technology breakthrough news 2026", max_results=5)
        if results:
            return f"\nTRENDING NOW (use as inspiration for a timely topic angle):\n{results}\n"
    except Exception:
        pass
    return ""


def genera_topic(strategy: dict = None, recent_topics: list = None) -> str:
    strategy = strategy or {}
    trending = _fetch_trending()
    angle = random.choice(_ANGLES)
    fmt = random.choice(_FORMATS)
    subtheme = random.choice(_SUBTHEMES)
    print(f"[cervello] Leve creative — tema:{subtheme} | angolo:{angle} | formato:{fmt}", flush=True)
    prompt = TOPIC_PROMPT.format(
        current_date=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        strategy_notes=strategy.get("notes", "Standard approach"),
        topic_focus=strategy.get("topic_focus", "AI and technology trends"),
        recent_topics=", ".join(recent_topics or []) or "none",
        trending_block=trending,
        angle=angle,
        fmt=fmt,
        subtheme=subtheme,
    )
    recent_norm = {t.strip().lower() for t in (recent_topics or [])}

    def _clean(t: str) -> str:
        # il modello a volte avvolge il topic in virgolette nonostante il prompt
        return t.strip().strip('"“”‘’\' ')

    topic = _clean(chat_ollama(prompt, max_tokens=64))
    # se ricasca su un topic recente, ritenta una volta con nuove leve casuali
    if topic.lower() in recent_norm:
        print(f"[cervello] Topic duplicato '{topic}', ritento con altre leve", flush=True)
        retry = prompt.replace(angle, random.choice(_ANGLES)).replace(subtheme, random.choice(_SUBTHEMES))
        alt = _clean(chat_ollama(retry, max_tokens=64))
        if alt and alt.lower() not in recent_norm:
            topic = alt
    return topic


def genera_contenuto(topic: str, strategy: dict = None) -> dict:
    strategy = strategy or {}
    try:
        from moduli.preferenze import carica
        pref = carica()
    except Exception:
        pref = {}
    target_minutes = pref.get("durata_target_minuti", 8)
    language = pref.get("lingua", "english") or "english"
    target_words = int(target_minutes * 130)  # ~130 parole/min a velocità TTS normale
    prompt = CONTENT_PROMPT.format(
        current_date=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        topic=topic,
        title_style=strategy.get("title_style", "curiosity-driven"),
        tone=strategy.get("tone", "confident and informative"),
        hook_strength=strategy.get("hook_strength", "medium"),
        strategy_notes=strategy.get("notes", "Standard approach"),
        target_minutes=target_minutes,
        target_words=target_words,
        language=language,
    )
    # uno script troppo corto produce un video di pochi secondi: meglio
    # ritentare una volta e poi fallire con un errore chiaro che pubblicarlo
    min_words = max(150, int(target_words * 0.5))
    last_err = None
    for attempt in range(2):
        try:
            content = _parse_json(chat_ollama(prompt, max_tokens=8192))
            words = len(content.get("script", "").split())
            if words < min_words:
                raise ValueError(
                    f"Script troppo corto: {words} parole, minimo {min_words} "
                    f"per un video da ~{target_minutes} minuti"
                )
            return content
        except ValueError as e:
            last_err = e
            print(f"[cervello] Contenuto non valido (tentativo {attempt + 1}/2): {e}", flush=True)
    raise last_err
