import os
import urllib.parse
import requests
import textwrap
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

THUMB_W, THUMB_H = 1280, 720
FONT_PATH = "assets/font_bold.ttf"
SHADOW_OFFSET = 3


_MOOD_VISUALS = {
    "epic":       "epic cinematic, dramatic god rays, intense lighting",
    "chill":      "soft pastel colors, calm atmosphere, soothing tones",
    "mysterious": "dark mysterious, fog, neon highlights, eerie shadows",
    "upbeat":     "vibrant colors, energetic, bright optimistic lighting",
    "tense":      "high contrast, red accents, danger atmosphere",
}

def _fetch_image(title: str, mood: str = None, style: str = None) -> Image.Image:
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


def _draw_title(img: Image.Image, title: str) -> Image.Image:
    if img.size != (THUMB_W, THUMB_H):
        img = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
    img = img.convert("RGBA")
    font_size = _font_size_for_title(title)
    font = _get_font(font_size)

    # wrap basato su pixel width
    wrap_chars = max(12, int(THUMB_W * 0.85 / (font_size * 0.55)))
    lines = textwrap.wrap(title, width=wrap_chars)

    line_h = font_size + 12
    block_h = len(lines) * line_h + 20
    padding = 40

    # dark gradient strip on bottom half
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    strip_top = THUMB_H - block_h - padding * 2 - 30
    for y in range(strip_top, THUMB_H):
        alpha = int(210 * ((y - strip_top) / (THUMB_H - strip_top)))
        for x in range(THUMB_W):
            overlay.putpixel((x, y), (0, 0, 0, alpha))
    img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)
    y = THUMB_H - block_h - padding

    for line in lines:
        bbox = font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        x = (THUMB_W - line_w) // 2

        # stroke (outline)
        for dx in (-2, 0, 2):
            for dy in (-2, 0, 2):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 255))

        # shadow
        draw.text((x + SHADOW_OFFSET, y + SHADOW_OFFSET), line, font=font, fill=(0, 0, 0, 200))

        # text
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h

    return img.convert("RGB")


def genera_thumbnail(title: str, output_path: str, mood: str = None, style: str = None) -> None:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    img = _fetch_image(title, mood=mood, style=style)
    img = _draw_title(img, title)
    img.save(output_path, "JPEG", quality=95)
