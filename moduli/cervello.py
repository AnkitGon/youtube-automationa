
import json
import re
from datetime import datetime
from moduli.ai_client import chat_ollama

TOPIC_PROMPT = """You are a viral YouTube content strategist for a tech/AI channel.

Today's date: {current_date}
Current strategy guidance: {strategy_notes}
Topic focus: {topic_focus}

Generate ONE trending topic for a YouTube video about AI or technology.
Base your suggestion on what is relevant and trending as of {current_date}.
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

Reply ONLY with valid JSON, exact structure:
{{
  "title": "Compelling title, max 70 chars",
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


def genera_topic(strategy: dict = None, recent_topics: list = None) -> str:
    strategy = strategy or {}
    prompt = TOPIC_PROMPT.format(
        current_date=datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        strategy_notes=strategy.get("notes", "Standard approach"),
        topic_focus=strategy.get("topic_focus", "AI and technology trends"),
        recent_topics=", ".join(recent_topics or []) or "none",
    )
    return chat_ollama(prompt, max_tokens=64).strip()


def genera_contenuto(topic: str, strategy: dict = None) -> dict:
    strategy = strategy or {}
    try:
        from moduli.preferenze import carica
        target_minutes = carica().get("durata_target_minuti", 8)
    except Exception:
        target_minutes = 8
    target_words = int(target_minutes * 130)  # ~130 parole/min a velocità TTS normale
    prompt = CONTENT_PROMPT.format(
        current_date=datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        topic=topic,
        title_style=strategy.get("title_style", "curiosity-driven"),
        tone=strategy.get("tone", "confident and informative"),
        hook_strength=strategy.get("hook_strength", "medium"),
        strategy_notes=strategy.get("notes", "Standard approach"),
        target_minutes=target_minutes,
        target_words=target_words,
    )
    return _parse_json(chat_ollama(prompt, max_tokens=8192))
