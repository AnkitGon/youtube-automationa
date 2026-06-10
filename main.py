import os
import sys
from dotenv import load_dotenv

load_dotenv()

from moduli.cervello import genera_topic, genera_contenuto
from moduli.audio import genera_audio
from moduli.asset import scarica_clip
from moduli.montaggio import monta_video
from moduli.thumbnail import genera_thumbnail
from moduli.pubblica import pubblica_video
from moduli.analytics import leggi_performance
from moduli.strategia import calcola_strategia

AUDIO_PATH = "output/narration.mp3"
VIDEO_PATH = "output/output_finale.mp4"
THUMB_PATH = "output/thumbnail.jpg"


def run():
    os.makedirs("output", exist_ok=True)

    print("=== [Analytics] Reading channel performance ===")
    try:
        performance = leggi_performance(n_video=5)
        print(f"  {len(performance)} videos analyzed")
    except Exception as e:
        print(f"  Skipped (new channel): {e}")
        performance = []

    print("=== [Strategy] Adapting strategy ===")
    strategy = calcola_strategia(performance)
    print(f"  {strategy.get('notes', '')}")

    print("\n=== [A] Generating topic & content ===")
    topic = genera_topic(strategy=strategy)
    print(f"  Topic: {topic}")
    content = genera_contenuto(topic, strategy=strategy)
    print(f"  Title: {content['title']}")

    print("\n=== [B] Generating audio ===")
    genera_audio(content["script"], AUDIO_PATH)
    print(f"  Saved: {AUDIO_PATH}")

    print("\n=== [C] Fetching video clips ===")
    clip_paths = {}
    for kw in content["video_keywords"]:
        print(f"  Fetching: {kw}")
        try:
            clip_paths[kw] = scarica_clip(kw)
        except Exception as e:
            print(f"  WARNING skipped '{kw}': {e}")

    if not clip_paths:
        print("ERROR: No clips downloaded. Aborting.")
        sys.exit(1)

    print("\n=== [D] Rendering video ===")
    from moduli.manutenzione import assicura_spazio, pulisci_temp_render, spazio_libero_gb
    pulisci_temp_render("output")
    assicura_spazio(work_dir="output")
    print(f"  Disk free: {spazio_libero_gb('output'):.1f} GB")
    monta_video(AUDIO_PATH, list(clip_paths.keys()), clip_paths, VIDEO_PATH,
                mood=content.get("mood"), captions_text=content.get("script"))
    print(f"  Saved: {VIDEO_PATH}")

    print("\n=== [E] Generating thumbnail ===")
    genera_thumbnail(
        content["title"], THUMB_PATH,
        mood=content.get("mood"),
        thumbnail_description=content.get("thumbnail_description"),
        thumbnail_phrase=content.get("thumbnail_phrase"),
        thumbnail_font_size=content.get("thumbnail_font_size"),
    )
    print(f"  Saved: {THUMB_PATH}")

    print("\n=== [F] Publishing to YouTube ===")
    video_id = pubblica_video(VIDEO_PATH, THUMB_PATH, content)
    print(f"  Done: https://youtu.be/{video_id}")


if __name__ == "__main__":
    run()
