import os
import urllib.parse
import requests
import textwrap
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

THUMB_W, THUMB_H = 1280, 720
FONT_PATH = "assets/font_bold.ttf"
SHADOW_OFFSET = 3

HF_MODEL = "black-forest-labs/FLUX.1-schnell"
OPENROUTER_IMAGE_URL = "https://openrouter.ai/api/v1/images/generations"
OPENROUTER_IMAGE_MODEL = "black-forest-labs/flux-1-schnell"

_MOOD_VISUALS = {
    "epic":       "epic cinematic god rays, intense dramatic lighting, deep shadows",
    "chill":      "soft pastel colors, calm serene atmosphere, gentle diffused light",
    "mysterious": "dark mysterious fog, neon highlights, eerie blue-green shadows",
    "upbeat":     "vibrant saturated colors, energetic bright lighting, optimistic mood",
    "tense":      "high contrast red accents, danger atmosphere, harsh shadows",
}


def _image_provider() -> str:
    return os.environ.get("IMAGE_PROVIDER", "pollinations").lower()


def _build_ai_prompt(title: str, mood: str = None, style: str = None,
                     thumbnail_description: str = None) -> str:
    if thumbnail_description and len(thumbnail_description.strip()) > 40:
        return thumbnail_description.strip()
    mood_visual = _MOOD_VISUALS.get((mood or "").lower(),
                                    "dramatic cinematic lighting, deep atmospheric shadows")
    user_style = style or "cinematic dark moody, ultra-detailed"
    return (
        f"Professional YouTube thumbnail, photorealistic, ultra-detailed, 16:9 landscape. "
        f"Subject: {title}. Style: {user_style}. Mood: {mood_visual}. "
        f"Futuristic tech AI atmosphere, glowing neon accents, volumetric light rays, "
        f"sharp focus, vivid colors, bold visual impact, attention-grabbing composition, "
        f"cinematic 85mm lens perspective, rich depth of field. "
        f"No text, no watermarks, no logos."
    )


def _fetch_image_hf(prompt: str) -> Image.Image:
    from huggingface_hub import InferenceClient
    key = os.environ.get("HF_API_KEY", "")
    client = InferenceClient(token=key)
    img = client.text_to_image(
        prompt,
        model=HF_MODEL,
        width=THUMB_W,
        height=THUMB_H,
    )
    return img.convert("RGB")


def _fetch_image_openrouter(prompt: str) -> Image.Image:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_IMAGE_MODEL,
        "prompt": prompt,
        "size": f"{THUMB_W}x{THUMB_H}",
        "n": 1,
    }
    r = requests.post(OPENROUTER_IMAGE_URL, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    url = r.json()["data"][0]["url"]
    img_r = requests.get(url, timeout=60)
    img_r.raise_for_status()
    return Image.open(BytesIO(img_r.content)).convert("RGB")


def _fetch_image_pollinations(title: str, mood: str = None, style: str = None) -> Image.Image:
    mood_visual = _MOOD_VISUALS.get((mood or "").lower(), "cinematic dramatic lighting")
    user_style = style or "cinematic dramatic lighting, dark moody"
    prompt = (
        f"professional youtube thumbnail, {user_style}, {mood_visual}, "
        f"photorealistic high detail, tech AI futuristic background, "
        f"empty lower third space for text overlay, 16:9, "
        f"sharp focus, vivid colors, attention-grabbing composition, "
        f"subject: {title}"
    )
    url = (
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
        f"?width={THUMB_W}&height={THUMB_H}&nologo=true&enhance=true&model=flux"
    )
    r = requests.get(url, timeout=90)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGB")


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    for path in (FONT_PATH, "assets/font_bold.ttf", "arial.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _font_size_for_title(title: str) -> int:
    length = len(title)
    if length <= 30:
        return 95
    if length <= 50:
        return 80
    if length <= 70:
        return 68
    return 58


def _parse_color(color_str: str) -> tuple:
    _NOMI = {
        "bianco": (255, 255, 255), "nero": (0, 0, 0),
        "rosso": (255, 50, 50), "giallo": (255, 220, 0),
        "verde": (50, 255, 100), "blu": (50, 150, 255),
        "arancione": (255, 140, 0), "viola": (180, 50, 255),
        "cyan": (0, 220, 255), "rosa": (255, 100, 180),
        "white": (255, 255, 255), "red": (255, 50, 50),
        "yellow": (255, 220, 0), "blue": (50, 150, 255),
        "green": (50, 255, 100), "orange": (255, 140, 0),
    }
    s = color_str.strip().lower()
    if s in _NOMI:
        return _NOMI[s]
    parts = [p.strip() for p in s.split(",")]
    if len(parts) == 3:
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            pass
    return (255, 255, 255)


def _draw_title(img: Image.Image, title: str,
                text_color: tuple = (255, 255, 255),
                position: str = "basso") -> Image.Image:
    if img.size != (THUMB_W, THUMB_H):
        img = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
    img = img.convert("RGBA")
    font_size = _font_size_for_title(title)
    font = _get_font(font_size)

    wrap_chars = max(12, int(THUMB_W * 0.85 / (font_size * 0.55)))
    lines = textwrap.wrap(title, width=wrap_chars)

    line_h = font_size + 12
    block_h = len(lines) * line_h + 20
    padding = 40

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    if position == "alto":
        strip_end = block_h + padding * 2 + 30
        for y in range(0, strip_end):
            alpha = int(210 * ((strip_end - y) / strip_end))
            for x in range(THUMB_W):
                overlay.putpixel((x, y), (0, 0, 0, alpha))
        text_y_start = padding
    else:
        strip_top = THUMB_H - block_h - padding * 2 - 30
        for y in range(strip_top, THUMB_H):
            alpha = int(210 * ((y - strip_top) / (THUMB_H - strip_top)))
            for x in range(THUMB_W):
                overlay.putpixel((x, y), (0, 0, 0, alpha))
        text_y_start = THUMB_H - block_h - padding
    img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)
    fill_rgba = (*text_color, 255)
    y = text_y_start

    for line in lines:
        bbox = font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        x = (THUMB_W - line_w) // 2
        for dx in (-2, 0, 2):
            for dy in (-2, 0, 2):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 255))
        draw.text((x + SHADOW_OFFSET, y + SHADOW_OFFSET), line,
                  font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=font, fill=fill_rgba)
        y += line_h

    return img.convert("RGB")


def genera_thumbnail(title: str, output_path: str, mood: str = None,
                     style: str = None, thumbnail_description: str = None) -> None:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    provider = _image_provider()

    if provider == "huggingface":
        prompt = _build_ai_prompt(title, mood=mood, style=style,
                                  thumbnail_description=thumbnail_description)
        print(f"[FLUX/HF] {prompt[:120]}...", flush=True)
        img = _fetch_image_hf(prompt)

    elif provider == "openrouter":
        prompt = _build_ai_prompt(title, mood=mood, style=style,
                                  thumbnail_description=thumbnail_description)
        print(f"[FLUX/OR] {prompt[:120]}...", flush=True)
        img = _fetch_image_openrouter(prompt)

    else:
        img = _fetch_image_pollinations(title, mood=mood, style=style)

    try:
        from moduli.preferenze import carica as _carica_pref
        _pref = _carica_pref()
    except Exception:
        _pref = {}
    if _pref.get("thumbnail_testo_mostra", True):
        _color = _parse_color(_pref.get("thumbnail_testo_colore", "255,255,255"))
        _pos = _pref.get("thumbnail_testo_posizione", "basso")
        img = _draw_title(img, title, text_color=_color, position=_pos)

    if img.size != (THUMB_W, THUMB_H):
        img = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)

    img.save(output_path, "JPEG", quality=95)
