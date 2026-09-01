import os
import json
import hashlib
import requests

CACHE_DIR = "cache/pexels"
PEXELS_SEARCH = "https://api.pexels.com/videos/search"
INDEX_PATH = os.path.join(CACHE_DIR, "index.json")
MAX_DOWNLOAD_BYTES = int(os.environ.get("MAX_CLIP_DOWNLOAD_MB", "250")) * 1024 * 1024
# i segmenti del montaggio durano 5s: clip più corte vanno in loop visibile
MIN_CLIP_SECONDS = float(os.environ.get("MIN_CLIP_SECONDS", "5"))


def _filtra_durata(videos: list) -> list:
    """Preferisce clip lunghe almeno MIN_CLIP_SECONDS; se il filtro svuota
    tutto, restituisce la lista originale (meglio una clip corta che zero)."""
    lunghe = [v for v in videos if (v.get("duration") or 0) >= MIN_CLIP_SECONDS]
    return lunghe if lunghe else videos


def _load_index() -> dict:
    if os.path.exists(INDEX_PATH):
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_index(index: dict) -> None:
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def _cache_path(keyword: str) -> str:
    slug = hashlib.md5(keyword.encode()).hexdigest()[:12]
    return os.path.join(CACHE_DIR, f"{slug}.mp4")


def _cache_path_id(pexels_id) -> str:
    """Percorso cache per uno specifico video Pexels (clip distinte per id)."""
    return os.path.join(CACHE_DIR, f"pex_{pexels_id}.mp4")


def _existing_variant(path: str) -> str | None:
    for p in (path.replace('.mp4', '_720p.mp4'),
              path.replace('.mp4', '_1080p.mp4'),
              path):
        if os.path.exists(p):
            return p
    return None


def _cache_path_1080p(keyword: str) -> str:
    return _cache_path(keyword).replace('.mp4', '_1080p.mp4')


def _cache_variants(keyword: str) -> list[str]:
    base = _cache_path(keyword)
    return [
        base.replace('.mp4', '_720p.mp4'),
        base.replace('.mp4', '_1080p.mp4'),
        base,
    ]


def _download(url: str, dest: str) -> None:
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            content_type = r.headers.get("content-type", "")
            if content_type and "video" not in content_type and "octet-stream" not in content_type:
                raise RuntimeError(f"Unexpected clip content-type: {content_type}")
            expected = r.headers.get("content-length")
            if expected and int(expected) > MAX_DOWNLOAD_BYTES:
                raise RuntimeError(f"Clip too large: {int(expected) // (1024 * 1024)} MB")
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError(f"Clip exceeded limit: {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB")
                    f.write(chunk)
    except Exception:
        # niente file parziali in cache: verrebbero riusati come clip valide
        # nei run successivi e corromperebbero il montaggio
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
        raise


def _best_file(video_files: list, *, prefer_vertical: bool = False) -> str:
    if prefer_vertical:
        vertical = [
            v for v in video_files
            if v.get("height", 0) > v.get("width", 0) and v.get("height", 0) >= 720
        ]
        if vertical:
            vertical.sort(key=lambda v: v.get("height", 0), reverse=True)
            link = vertical[0].get("link")
            if link:
                return link
    hd = [v for v in video_files if v.get("quality") in ("hd", "uhd") and v.get("width", 0) >= 1280]
    pool = hd if hd else video_files
    if not pool:
        raise RuntimeError("No downloadable video files found in Pexels response")
    pool.sort(key=lambda v: v.get("width", 0), reverse=True)
    link = pool[0].get("link")
    if not link:
        raise RuntimeError("Pexels video file has no download link")
    return link


def _keyword_to_tags(keyword: str) -> list[str]:
    """Genera tag dal keyword: parole singole + keyword intera."""
    words = [w.lower() for w in keyword.split() if len(w) > 2]
    return list(dict.fromkeys([keyword.lower()] + words))


def _find_cached_by_tags(tags: list[str], index: dict) -> str | None:
    """Cerca nella cache una clip i cui tag matchano almeno uno dei tag richiesti."""
    query_tags = {t.lower() for t in tags}
    for kw, meta in index.items():
        clip_tags = {t.lower() for t in meta.get("tags", [])}
        if clip_tags & query_tags:
            # verifica che il file esista ancora
            path_orig = os.path.join(CACHE_DIR, meta.get("file", ""))
            variants = [
                path_orig.replace('.mp4', '_720p.mp4'),
                path_orig.replace('.mp4', '_1080p.mp4'),
                path_orig,
            ]
            for path in variants:
                if os.path.exists(path):
                    return path
    return None


def _fetch_metadata(keyword: str, headers: dict, *, orientation: str = "landscape") -> dict | None:
    for size in ("large", "medium"):
        params = {"query": keyword, "orientation": orientation, "per_page": 5, "size": size}
        try:
            r = requests.get(PEXELS_SEARCH, headers=headers, params=params, timeout=15)
            r.raise_for_status()
            videos = r.json().get("videos", [])
            if videos:
                v = videos[0]
                return {
                    "file": os.path.basename(_cache_path(keyword)),
                    "pexels_id": v.get("id"),
                    "url": v.get("url"),
                    "duration": v.get("duration"),
                    "author": v.get("user", {}).get("name"),
                    "tags": _keyword_to_tags(keyword),
                }
        except Exception:
            pass
    return None


def scarica_clip(keyword: str, extra_tags: list[str] | None = None) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(keyword)
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not set — run 'tube-assistant onboard' to configure")
    headers = {"Authorization": api_key}
    index = _load_index()

    # cerca prima nella cache per keyword esatta
    cached = next((p for p in _cache_variants(keyword) if os.path.exists(p)), None)
    if cached:
        if keyword not in index:
            meta = _fetch_metadata(keyword, headers)
            if meta:
                index[keyword] = meta
                _save_index(index)
        else:
            # aggiorna i tag se mancano
            entry = index[keyword]
            if not entry.get("tags"):
                entry["tags"] = _keyword_to_tags(keyword)
                if extra_tags:
                    entry["tags"] = list(dict.fromkeys(entry["tags"] + [t.lower() for t in extra_tags]))
                _save_index(index)
        return cached

    # cerca nella cache per tag semantici prima di scaricare
    all_tags = _keyword_to_tags(keyword) + (extra_tags or [])
    match = _find_cached_by_tags(all_tags, index)
    if match:
        return match

    # download da Pexels
    params = {"query": keyword, "orientation": "landscape", "per_page": 5, "size": "large"}
    r = requests.get(PEXELS_SEARCH, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    videos = r.json().get("videos", [])

    if not videos:
        params["size"] = "medium"
        r = requests.get(PEXELS_SEARCH, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        videos = r.json().get("videos", [])

    if not videos:
        raise RuntimeError(f"No Pexels results for: {keyword}")
    videos = _filtra_durata(videos)

    link = _best_file(videos[0]["video_files"])
    _download(link, path)

    tags = _keyword_to_tags(keyword)
    if extra_tags:
        tags = list(dict.fromkeys(tags + [t.lower() for t in extra_tags]))

    index[keyword] = {
        "file": os.path.basename(path),
        "pexels_id": videos[0].get("id"),
        "url": videos[0].get("url"),
        "duration": videos[0].get("duration"),
        "author": videos[0].get("user", {}).get("name"),
        "tags": tags,
    }
    _save_index(index)

    return path


def scarica_clips(
    keyword: str,
    max_n: int = 3,
    extra_tags: list[str] | None = None,
    *,
    orientation: str = "landscape",
) -> list[str]:
    """Scarica fino a max_n clip DISTINTE per il keyword (per arricchire il pool
    ed evitare ripetizioni nel montaggio). Ogni clip e' un file fisico diverso,
    indicizzato per id Pexels. Ritorna la lista dei path scaricati/cached."""
    prefer_vertical = orientation == "portrait"
    os.makedirs(CACHE_DIR, exist_ok=True)
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not set — run 'tube-assistant onboard' to configure")
    headers = {"Authorization": api_key}
    index = _load_index()

    videos = []
    for size in ("large", "medium"):
        params = {"query": keyword, "orientation": orientation,
                  "per_page": max(max_n, 5), "size": size}
        try:
            r = requests.get(PEXELS_SEARCH, headers=headers, params=params, timeout=15)
            r.raise_for_status()
            videos = r.json().get("videos", [])
        except Exception:
            videos = []
        if videos:
            break

    if not videos:
        raise RuntimeError(f"No Pexels results for: {keyword}")
    videos = _filtra_durata(videos)

    tags = _keyword_to_tags(keyword)
    if extra_tags:
        tags = list(dict.fromkeys(tags + [t.lower() for t in extra_tags]))

    paths = []
    for v in videos[:max_n]:
        vid = v.get("id")
        if vid is None:
            continue
        dest = _cache_path_id(vid)
        cached = _existing_variant(dest)
        if cached:
            paths.append(cached)
        else:
            try:
                link = _best_file(v["video_files"], prefer_vertical=prefer_vertical)
                _download(link, dest)
                paths.append(dest)
            except Exception as e:
                print(f"[asset] clip {vid} saltata: {e}", flush=True)
                continue
        index[f"pex_{vid}"] = {
            "file": os.path.basename(dest),
            "pexels_id": vid,
            "url": v.get("url"),
            "duration": v.get("duration"),
            "author": v.get("user", {}).get("name"),
            "tags": tags,
        }

    if paths:
        _save_index(index)
    return paths


def rebuild_index(keywords: list[str]) -> dict:
    os.makedirs(CACHE_DIR, exist_ok=True)
    headers = {"Authorization": os.environ["PEXELS_API_KEY"]}
    index = _load_index()
    updated = 0

    for keyword in keywords:
        path = _cache_path(keyword)
        entry = index.get(keyword, {})
        if os.path.exists(path) and keyword not in index:
            meta = _fetch_metadata(keyword, headers)
            if meta:
                index[keyword] = meta
                updated += 1
        elif keyword in index and not entry.get("tags"):
            index[keyword]["tags"] = _keyword_to_tags(keyword)
            updated += 1

    if updated:
        _save_index(index)

    return {"total": len(index), "added": updated}
