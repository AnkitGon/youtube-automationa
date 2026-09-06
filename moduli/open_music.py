"""
Free Open-License Music Provider (Wikimedia Commons & Free Music API).

Fetches 100% royalty-free, public domain / CC-BY ambient tracks directly from the web
and caches them locally per mood. Rotates dynamically to prevent repetition.
"""

from __future__ import annotations

import os
import random
import re
import requests

MUSIC_CACHE_DIR = "cache/music"

# Curated royalty-free, public domain & CC-BY open audio tracks for each mood
OPEN_MUSIC_REGISTRY: dict[str, list[dict[str, str]]] = {
    "chill": [
        {"name": "Erik Satie - Gymnopédie No. 1", "url": "https://upload.wikimedia.org/wikipedia/commons/3/36/Erik_Satie_-_gymnopedie_no_1.ogg"},
        {"name": "Kevin MacLeod - Quiet Thought", "url": "https://upload.wikimedia.org/wikipedia/commons/e/e4/Quiet_Thought.ogg"},
        {"name": "Erik Satie - Gymnopédie No. 2", "url": "https://upload.wikimedia.org/wikipedia/commons/e/e8/Erik_Satie_-_gymnopedie_no_2.ogg"},
        {"name": "Erik Satie - Gymnopédie No. 3", "url": "https://upload.wikimedia.org/wikipedia/commons/e/e9/Erik_Satie_-_gymnopedie_no_3.ogg"},
        {"name": "Kevin MacLeod - Windswept", "url": "https://upload.wikimedia.org/wikipedia/commons/7/7d/Windswept.ogg"},
        {"name": "Kevin MacLeod - Deep Space", "url": "https://upload.wikimedia.org/wikipedia/commons/8/87/Deep_Space.ogg"},
    ],
    "epic": [
        {"name": "Modest Mussorgsky - Night on Bald Mountain", "url": "https://upload.wikimedia.org/wikipedia/commons/7/75/Mussorgsky_Night_on_Bald_Mountain.ogg"},
        {"name": "Holst - The Planets, Mars", "url": "https://upload.wikimedia.org/wikipedia/commons/b/b5/Holst_The_Planets_Mars_the_Bringer_of_War.ogg"},
        {"name": "Wagner - Ride of the Valkyries", "url": "https://upload.wikimedia.org/wikipedia/commons/5/52/Ride_of_the_Valkyries.ogg"},
        {"name": "Tchaikovsky - 1812 Overture Finale", "url": "https://upload.wikimedia.org/wikipedia/commons/1/1a/Tchaikovsky_1812_Overture_Finale.ogg"},
        {"name": "Dvorak - New World Symphony 4th Mvt", "url": "https://upload.wikimedia.org/wikipedia/commons/7/77/Dvorak_Symphony_9_Movement_4.ogg"},
        {"name": "Beethoven - Egmont Overture", "url": "https://upload.wikimedia.org/wikipedia/commons/8/87/Beethoven_Egmont_Overture.ogg"},
    ],
    "mysterious": [
        {"name": "Debussy - Clair de Lune", "url": "https://upload.wikimedia.org/wikipedia/commons/7/7c/Claude_Debussy_-_Clair_de_lune.ogg"},
        {"name": "Satie - Gnossienne No. 1", "url": "https://upload.wikimedia.org/wikipedia/commons/d/d8/Erik_Satie_-_Gnossienne_1.ogg"},
        {"name": "Satie - Gnossienne No. 2", "url": "https://upload.wikimedia.org/wikipedia/commons/3/30/Erik_Satie_-_Gnossienne_2.ogg"},
        {"name": "Satie - Gnossienne No. 3", "url": "https://upload.wikimedia.org/wikipedia/commons/a/a2/Erik_Satie_-_Gnossienne_3.ogg"},
        {"name": "Debussy - Preludes Book 1 Voiles", "url": "https://upload.wikimedia.org/wikipedia/commons/3/3a/Debussy_Voiles.ogg"},
        {"name": "Chopin - Nocturne Op 9 No 2", "url": "https://upload.wikimedia.org/wikipedia/commons/0/07/Chopin_Nocturne_Op_9_No_2.ogg"},
    ],
    "tense": [
        {"name": "Beethoven - Symphony No. 5 1st Movement", "url": "https://upload.wikimedia.org/wikipedia/commons/5/5a/Beethoven_5th_Symphony_Movement_1.ogg"},
        {"name": "Bach - Toccata and Fugue in D minor", "url": "https://upload.wikimedia.org/wikipedia/commons/8/8e/Toccata_and_Fugue_in_D_minor_BWV_565.ogg"},
        {"name": "Grieg - In the Hall of the Mountain King", "url": "https://upload.wikimedia.org/wikipedia/commons/c/c3/Grieg_In_the_Hall_of_the_Mountain_King.ogg"},
        {"name": "Stravinsky - The Rite of Spring Sacrificial Dance", "url": "https://upload.wikimedia.org/wikipedia/commons/4/4b/Stravinsky_Rite_of_Spring.ogg"},
        {"name": "Mozart - Requiem Dies Irae", "url": "https://upload.wikimedia.org/wikipedia/commons/a/a5/Mozart_Requiem_Dies_Irae.ogg"},
    ],
    "upbeat": [
        {"name": "Vivaldi - Four Seasons Spring", "url": "https://upload.wikimedia.org/wikipedia/commons/3/3b/Vivaldi_Four_Seasons_Spring_mvt_1_Allegro.ogg"},
        {"name": "Mozart - Eine kleine Nachtmusik", "url": "https://upload.wikimedia.org/wikipedia/commons/6/6b/Mozart_Eine_kleine_Nachtmusik_1st_movement.ogg"},
        {"name": "Rossini - William Tell Overture", "url": "https://upload.wikimedia.org/wikipedia/commons/d/d4/Rossini_William_Tell_Overture.ogg"},
        {"name": "Johann Strauss II - The Blue Danube", "url": "https://upload.wikimedia.org/wikipedia/commons/1/11/Blue_Danube.ogg"},
        {"name": "Bach - Brandenburg Concerto No 3", "url": "https://upload.wikimedia.org/wikipedia/commons/0/0e/Bach_Brandenburg_Concerto_3.ogg"},
    ],
}

_RECENTLY_USED_TRACKS: list[str] = []


def get_open_license_music(mood: str | None = None) -> str | None:
    """
    Fetches an open-license royalty-free background track based on mood.
    Rotates tracks so songs do not repeat across consecutive videos.
    Returns absolute path to local cached track or None.
    """
    global _RECENTLY_USED_TRACKS
    os.makedirs(MUSIC_CACHE_DIR, exist_ok=True)
    mood_key = (mood or "").lower().strip()
    if mood_key not in OPEN_MUSIC_REGISTRY:
        mood_key = random.choice(list(OPEN_MUSIC_REGISTRY.keys()))

    tracks = OPEN_MUSIC_REGISTRY[mood_key]
    
    # Filter out recently used tracks to prevent repetition
    available = [t for t in tracks if t["url"] not in _RECENTLY_USED_TRACKS]
    if not available:
        available = tracks
        _RECENTLY_USED_TRACKS.clear()

    track = random.choice(available)
    url = track["url"]
    _RECENTLY_USED_TRACKS.append(url)
    if len(_RECENTLY_USED_TRACKS) > 10:
        _RECENTLY_USED_TRACKS.pop(0)

    # Sanitize filename
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", track["name"])
    ext = os.path.splitext(url)[1] or ".ogg"
    local_path = os.path.join(MUSIC_CACHE_DIR, f"{safe_name}{ext}")

    if os.path.exists(local_path) and os.path.getsize(local_path) > 100_000:
        return os.path.abspath(local_path)

    try:
        print(f"[open_music] Downloading royalty-free open track '{track['name']}' ({mood_key})...", flush=True)
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200 and len(resp.content) > 100_000:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            print(f"[open_music] Cached to {local_path}", flush=True)
            return os.path.abspath(local_path)
    except Exception as e:
        print(f"[open_music] Download error: {e}", flush=True)

    return None
