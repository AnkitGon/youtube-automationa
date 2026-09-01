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
    """OpenRouter image gen via chat-completions modalities (no /images endpoint)."""
    import base64
    key = os.environ.get("OPENROUTER_API_KEY", "")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_IMAGE_MODEL,
        "modalities": ["image", "text"],
        "messages": [{"role": "user", "content": prompt}],
    }
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                      headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    images = msg.get("images") or []
    if not images:
        raise RuntimeError("OpenRouter: nessuna immagine nella risposta")
    url = images[0]["image_url"]["url"]
    if url.startswith("data:"):
        b64 = url.split(",", 1)[1]
        return Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")
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
    # Anonymous tier ora ha coda max=1 (402). Token gratuito da enter.pollinations.ai
    # passato via POLLINATIONS_TOKEN sblocca l'accesso.
    headers = {}
    token = os.environ.get("POLLINATIONS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers, timeout=90)
    r.raise_for_status()
    ct = r.headers.get("content-type", "")
    if "image" not in ct:
        raise RuntimeError(f"Pollinations non-image response: {r.text[:160]}")
    return Image.open(BytesIO(r.content)).convert("RGB")


def _fetch_image_da_clip() -> Image.Image:
    """Estrae un frame da una clip Pexels in cache: sfondo vero invece del
    gradiente quando tutti i provider AI falliscono."""
    import glob
    import subprocess
    import tempfile
    from moduli.ffmpeg_utils import ffmpeg_path
    cache_dir = os.environ.get("CACHE_DIR", "cache/pexels")
    clips = sorted(glob.glob(os.path.join(cache_dir, "*.mp4")),
                   key=os.path.getmtime, reverse=True)
    if not clips:
        raise RuntimeError("nessuna clip in cache per estrarre un frame")
    last_err = None
    for clip in clips[:5]:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            frame_path = tmp.name
        try:
            r = subprocess.run(
                [ffmpeg_path(), "-y", "-ss", "1", "-i", clip,
                 "-frames:v", "1", "-q:v", "2",
                 "-vf", f"scale={THUMB_W}:{THUMB_H}:force_original_aspect_ratio=increase,"
                        f"crop={THUMB_W}:{THUMB_H}",
                 frame_path],
                capture_output=True, timeout=60,
            )
            if r.returncode == 0 and os.path.getsize(frame_path) > 0:
                with Image.open(frame_path) as im:
                    return im.convert("RGB")
            last_err = RuntimeError(f"ffmpeg frame extract fallito su {clip}")
        except Exception as e:
            last_err = e
        finally:
            try:
                os.remove(frame_path)
            except OSError:
                pass
    raise last_err or RuntimeError("estrazione frame fallita")


def _fetch_image_placeholder(title: str, mood: str = None, **_) -> Image.Image:
    """Sfondo gradiente generato localmente — nessuna rete. Ultima spiaggia
    cosi' una copertina viene SEMPRE prodotta (testo overlay sopra)."""
    palettes = {
        "epic":       ((10, 5, 30),   (90, 20, 60)),
        "chill":      ((20, 40, 60),  (60, 110, 130)),
        "mysterious": ((5, 15, 25),   (15, 60, 70)),
        "upbeat":     ((40, 10, 60),  (130, 40, 90)),
        "tense":      ((30, 5, 5),    (90, 15, 15)),
    }
    top, bot = palettes.get((mood or "").lower(), ((8, 12, 28), (35, 50, 90)))
    col = Image.new("RGB", (1, THUMB_H))
    px = col.load()
    for y in range(THUMB_H):
        t = y / (THUMB_H - 1)
        px[0, y] = (
            int(top[0] + (bot[0] - top[0]) * t),
            int(top[1] + (bot[1] - top[1]) * t),
            int(top[2] + (bot[2] - top[2]) * t),
        )
    return col.resize((THUMB_W, THUMB_H))


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        FONT_PATH,
        "assets/font_bold.ttf",
        # Linux / Raspberry Pi OS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        # Windows
        "arial.ttf",
        "arialbd.ttf",
        r"C:\Windows\Fonts\ariblk.ttf",   # Arial Black
        r"C:\Windows\Fonts\arialbd.ttf",  # Arial Bold
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\impact.ttf",
        r"C:\Windows\Fonts\verdanab.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    # Pillow >= 10.1: default vettoriale scalabile. Il vecchio load_default()
    # senza size e' un bitmap ~11px: su sistemi senza i font sopra il testo
    # diventava microscopico.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


_FONT_PRESETS = {"A": 240, "B": 200, "C": 160, "D": 120}


def _fit_title(title: str, max_w: int, max_h: int,
               max_lines: int = 3, max_start: int = 80) -> tuple:
    """Trova il font piu' grande possibile che sta in max_w x max_h.
    Ritorna (font, lines, font_size). Testo mai tagliato."""
    title = " ".join(title.split())
    best = None
    for size in range(max_start, 39, -4):
        font = _get_font(size)
        # quanti caratteri per riga a questo size (stima su larghezza media)
        avg_char = max(1, size * 0.55)
        wrap_chars = max(8, int(max_w / avg_char))
        lines = textwrap.wrap(title, width=wrap_chars)
        if len(lines) > max_lines:
            continue
        # misura reale
        widest = 0
        for ln in lines:
            bb = font.getbbox(ln)
            widest = max(widest, bb[2] - bb[0])
        line_h = size + 12
        block_h = len(lines) * line_h
        if widest <= max_w and block_h <= max_h:
            best = (font, lines, size)
            break
    if best is None:
        # fallback: testo sempre visibile, mai tagliato
        font = _get_font(44)
        lines = textwrap.wrap(title, width=max(8, int(max_w / (44 * 0.55))))
        best = (font, lines, 44)
    return best


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
                position: str = "basso", scale: float = 1.0,
                font_size_preset: str = "C") -> Image.Image:
    if img.size != (THUMB_W, THUMB_H):
        img = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
    img = img.convert("RGBA")

    max_text_w = int(THUMB_W * 0.90)
    max_text_h = int(THUMB_H * 0.55)  # più alto = più righe disponibili, mai tagliato
    max_start = _FONT_PRESETS.get((font_size_preset or "C").strip().upper(), _FONT_PRESETS["C"])
    font, lines, font_size = _fit_title(title, max_text_w, max_text_h, max_start=max_start)

    # scala manuale opzionale (0.3-1.0)
    scale = max(0.3, min(1.0, scale))
    if scale < 0.999:
        font_size = max(24, int(font_size * scale))
        font = _get_font(font_size)
        wrap_chars = max(8, int(max_text_w / (font_size * 0.55)))
        lines = textwrap.wrap(" ".join(title.split()), width=wrap_chars)

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

    outline = max(2, font_size // 22)  # contorno proporzionale al font
    shadow = max(SHADOW_OFFSET, font_size // 24)

    for line in lines:
        bbox = font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        x = (THUMB_W - line_w) // 2
        for dx in range(-outline, outline + 1):
            for dy in range(-outline, outline + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 255))
        draw.text((x + shadow, y + shadow), line,
                  font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=font, fill=fill_rgba)
        y += line_h

    return img.convert("RGB")


def genera_thumbnail(title: str, output_path: str, mood: str = None,
                     style: str = None, thumbnail_description: str = None,
                     thumbnail_phrase: str = None,
                     thumbnail_font_size: str = None,
                     strategy: dict = None) -> None:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    try:
        from moduli.preferenze import carica as _carica_pref
        _pref = _carica_pref()
    except Exception:
        _pref = {}
    # la preferenza utente `stile_thumbnail` guida lo stile quando il chiamante
    # non ne passa uno esplicito
    if not style:
        style = _pref.get("stile_thumbnail") or None
    prompt = _build_ai_prompt(title, mood=mood, style=style,
                              thumbnail_description=thumbnail_description)
    if strategy:
        try:
            from moduli.avoid_patterns import find_avoid_match, collect_avoid_patterns
            patterns = collect_avoid_patterns(strategy)
            hit = find_avoid_match(prompt, patterns) or find_avoid_match(thumbnail_phrase or "", patterns)
            if hit:
                print(
                    f"[thumbnail] Prompt matches avoid pattern '{hit}' — using generic visual fallback",
                    flush=True,
                )
                prompt = _build_ai_prompt(title, mood=mood, style=style, thumbnail_description=None)
        except Exception:
            pass

    # Catena di fallback: provider configurato -> altri AI -> gradiente locale.
    # Garantisce che una copertina venga SEMPRE prodotta (mai "non fa niente").
    providers = {
        "huggingface": ("FLUX/HF", lambda: _fetch_image_hf(prompt)),
        "openrouter":  ("FLUX/OR", lambda: _fetch_image_openrouter(prompt)),
        "pollinations": ("POLLINATIONS",
                         lambda: _fetch_image_pollinations(title, mood=mood, style=style)),
    }
    order = [_image_provider()] + [p for p in providers if p != _image_provider()]

    img = None
    for name in order:
        if name not in providers:
            continue
        label, fetch = providers[name]
        try:
            print(f"[{label}] {prompt[:100]}...", flush=True)
            img = fetch()
            break
        except Exception as e:
            print(f"[{label}] fallito: {e}", flush=True)

    if img is None:
        try:
            print("[THUMBNAIL] provider AI falliti — provo frame da clip in cache", flush=True)
            img = _fetch_image_da_clip()
        except Exception as e:
            print(f"[THUMBNAIL] frame da clip fallito ({e}) — uso gradiente locale", flush=True)
            img = _fetch_image_placeholder(title, mood=mood)

    if _pref.get("thumbnail_testo_mostra", True):
        _color = _parse_color(_pref.get("thumbnail_testo_colore", "255,255,255"))
        _pos = _pref.get("thumbnail_testo_posizione", "basso")
        try:
            _scala = float(_pref.get("thumbnail_testo_scala", 1.0))
        except (TypeError, ValueError):
            _scala = 1.0
        _testo = (thumbnail_phrase or "").strip() or title
        # pref vince su scelta LLM se impostata, altrimenti LLM, altrimenti C
        _preset = _pref.get("thumbnail_font_size") or thumbnail_font_size or "C"
        img = _draw_title(img, _testo, text_color=_color, position=_pos,
                          scale=_scala, font_size_preset=_preset)

    if img.size != (THUMB_W, THUMB_H):
        img = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)

    img.save(output_path, "JPEG", quality=95)
