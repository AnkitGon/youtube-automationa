
import json
import re
from moduli.ai_client import chat_ollama

TOPIC_PROMPT = """You are a viral YouTube content strategist for a tech/AI channel.

Current strategy guidance: {strategy_notes}
Topic focus: {topic_focus}

Generate ONE trending topic for a YouTube video about AI or technology.
Avoid repeating these recent topics: {recent_topics}
Reply with ONLY the topic as a short phrase (3-7 words). No explanation, no punctuation."""

CONTENT_PROMPT = """You are a viral YouTube scriptwriter for a tech/AI channel.
Create a complete video about: {topic}

Strategy guidance:
- Title style: {title_style}
- Tone: {tone}
- Hook strength: {hook_strength}
- Notes: {strategy_notes}

Reply ONLY with valid JSON, exact structure:
{{
  "title": "Compelling title, max 70 chars",
  "description": "SEO-optimized description, 200-300 words, include keywords naturally",
  "tags": ["tag1", "tag2", "tag3"],
  "script": "Full narration in English. Engaging, clear, conversational. Target 8 minutes = ~1100-1200 words. No headers or sections, flowing prose.",
  "video_keywords": [
    "AI neural network visualization",
    "futuristic city technology",
    "scientist working computer"
  ]
}}

Rules:
- title: follow the title_style guidance above
- tags: 12-15 relevant tags
- script: exactly 1100-1200 words, engaging pace, no bullet points
- video_keywords: 12-18 unique English phrases describing stock video scenes (2-4 words each, concrete and visual)
"""


def _parse_json(text: str) -> dict:
    print(f"[DEBUG raw response]\n{text[:500]}\n---", flush=True)
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError("No JSON found in model response")
    return json.loads(match.group())


def genera_topic(strategy: dict = None, recent_topics: list = None) -> str:
    strategy = strategy or {}
    prompt = TOPIC_PROMPT.format(
        strategy_notes=strategy.get("notes", "Standard approach"),
        topic_focus=strategy.get("topic_focus", "AI and technology trends"),
        recent_topics=", ".join(recent_topics or []) or "none",
    )
    return chat_ollama(prompt, max_tokens=64).strip()


def genera_contenuto(topic: str, strategy: dict = None) -> dict:
    strategy = strategy or {}
    prompt = CONTENT_PROMPT.format(
        topic=topic,
        title_style=strategy.get("title_style", "curiosity-driven"),
        tone=strategy.get("tone", "confident and informative"),
        hook_strength=strategy.get("hook_strength", "medium"),
        strategy_notes=strategy.get("notes", "Standard approach"),
    )
    return _parse_json(chat_ollama(prompt, max_tokens=8192))
