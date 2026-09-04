"""Manutenzione disco: guardia spazio + pulizia cache.

Evita il crash `OSError: [Errno 28] No space left on device` durante il
montaggio. Tutto configurabile via env, default sensati per chiunque:

  MIN_FREE_DISK_GB     spazio minimo libero richiesto prima del montaggio (default 5)
  MAX_CACHE_MB         tetto massimo della cache clip Pexels (default 2000 = 2GB)
  CACHE_DIR            cartella cache (default cache/pexels)
"""

import os
import glob
import shutil
import time

CACHE_DIR = os.environ.get("CACHE_DIR", "cache/pexels")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


MIN_FREE_DISK_GB = _env_float("MIN_FREE_DISK_GB", 5.0)
MAX_CACHE_MB = _env_float("MAX_CACHE_MB", 2000.0)


def spazio_libero_gb(path: str = ".") -> float:
    """GB liberi sul filesystem che contiene `path`."""
    try:
        target = path if os.path.exists(path) else "."
        free = shutil.disk_usage(target).free
        return free / (1024 ** 3)
    except OSError:
        return float("inf")  # non blocchiamo se non riusciamo a leggere


def assicura_spazio(min_gb: float = None, work_dir: str = "output", protetti: set = None) -> None:
    """Se lo spazio libero e' sotto la soglia, prima prova a liberare la cache,
    poi rilancia un errore chiaro. Da chiamare PRIMA del montaggio (lo step che
    riempie il disco con i file temporanei di render). `protetti` = clip che
    servono alla run corrente, mai cancellate."""
    min_gb = MIN_FREE_DISK_GB if min_gb is None else min_gb
    libero = spazio_libero_gb(work_dir)
    if libero >= min_gb:
        return
    # tentativo di recupero: svuota la cache clip (tranne le clip protette)
    liberati = pulisci_cache(max_mb=0, protetti=protetti)
    libero = spazio_libero_gb(work_dir)
    if libero >= min_gb:
        return
    raise RuntimeError(
        f"Spazio disco insufficiente: {libero:.1f} GB liberi, ne servono almeno "
        f"{min_gb:.1f} GB per il montaggio. Liberati {liberati:.0f} MB di cache "
        f"ma non basta. Libera spazio sul disco e riprova con /forza."
    )


def _cache_files() -> list[str]:
    if not os.path.isdir(CACHE_DIR):
        return []
    return [p for p in glob.glob(os.path.join(CACHE_DIR, "*.mp4")) if os.path.isfile(p)]


def cache_size_mb() -> float:
    return sum(os.path.getsize(p) for p in _cache_files()) / (1024 ** 2)


def pulisci_cache(max_mb: float = None, protetti: set = None) -> float:
    """Tiene la cache clip sotto `max_mb` cancellando i file piu' vecchi (LRU per
    mtime). `max_mb=0` svuota tutto. I path in `protetti` (clip che servono alla
    run corrente) non vengono mai cancellati. Ritorna i MB liberati."""
    max_mb = MAX_CACHE_MB if max_mb is None else max_mb
    protetti_abs = {os.path.abspath(p) for p in (protetti or ())}
    files = _cache_files()
    if not files:
        return 0.0
    total = sum(os.path.getsize(p) for p in files)
    limit = max_mb * 1024 ** 2
    if total <= limit:
        return 0.0
    # piu' vecchi prima
    files.sort(key=lambda p: os.path.getmtime(p))
    liberati = 0
    for p in files:
        if total <= limit:
            break
        if os.path.abspath(p) in protetti_abs:
            continue
        try:
            sz = os.path.getsize(p)
            os.remove(p)
            total -= sz
            liberati += sz
        except OSError:
            continue
    return liberati / (1024 ** 2)


def pulisci_temp_render(work_dir: str = "output") -> int:
    """Rimuove cartelle temporanee di render orfane (render_*) lasciate da crash
    precedenti. Ritorna quante ne ha rimosse."""
    rimosse = 0
    if not os.path.isdir(work_dir):
        return 0
    for name in os.listdir(work_dir):
        if name.startswith("render_"):
            full = os.path.join(work_dir, name)
            try:
                if os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
                else:
                    os.remove(full)
                rimosse += 1
            except OSError:
                continue
    return rimosse


# ── Daily runtime purge (cache/ + output/) ───────────────────────────────────

OUTPUT_DIR = "output"
CACHE_ROOT = "cache"
SCAFFOLD_AFTER_PURGE = (
    "output",
    "output/shorts",
    "cache",
    "cache/pexels",
    "cache/shorts",
)


def daily_cleanup_enabled() -> bool:
    raw = os.environ.get("DAILY_CLEANUP_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def daily_cleanup_hour() -> int:
    try:
        return max(0, min(23, int(os.environ.get("DAILY_CLEANUP_HOUR", "1"))))
    except (TypeError, ValueError):
        return 1


def daily_cleanup_timezone_name() -> str:
    return (
        os.environ.get("DAILY_CLEANUP_TIMEZONE", "").strip()
        or os.environ.get("DEFAULT_PUBLISH_TIMEZONE", "").strip()
        or os.environ.get("SHORTS_TIMEZONE", "").strip()
        or "Asia/Kolkata"
    )


def wipe_dir_contents(path: str) -> tuple[int, float]:
    """Delete everything inside `path` (keep the directory). Returns (items, MB)."""
    if not os.path.isdir(path):
        return 0, 0.0
    removed = 0
    bytes_freed = 0
    for name in os.listdir(path):
        full = os.path.join(path, name)
        try:
            if os.path.isfile(full) or os.path.islink(full):
                bytes_freed += os.path.getsize(full)
                os.remove(full)
                removed += 1
            elif os.path.isdir(full):
                for root, _dirs, files in os.walk(full):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            bytes_freed += os.path.getsize(fp)
                        except OSError:
                            pass
                shutil.rmtree(full, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed, bytes_freed / (1024 ** 2)


def purge_runtime_dirs(
    *,
    output_dir: str = OUTPUT_DIR,
    cache_dir: str = CACHE_ROOT,
) -> dict:
    """
    Wipe cache/ and output/ contents, then recreate scaffold folders.
    Safe for models: learning/state/secrets live outside these dirs.
    """
    out_n, out_mb = wipe_dir_contents(output_dir)
    cache_n, cache_mb = wipe_dir_contents(cache_dir)
    for d in SCAFFOLD_AFTER_PURGE:
        os.makedirs(d, exist_ok=True)
    return {
        "output_items": out_n,
        "output_mb": round(out_mb, 1),
        "cache_items": cache_n,
        "cache_mb": round(cache_mb, 1),
        "freed_mb": round(out_mb + cache_mb, 1),
    }


def is_pipeline_busy(
    *,
    longform_state: dict | None = None,
    shorts_state: dict | None = None,
    checkpoint_path: str = "output/pipeline_checkpoint.json",
    now_utc=None,
) -> tuple[bool, str]:
    """
    True when deleting cache/output would risk an active or resumable run.
    Uses status flags (not fixed schedule hours) so dynamic triggers stay safe.
    """
    from datetime import datetime, timezone

    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")

    if longform_state and longform_state.get("pipeline_status"):
        step = (longform_state.get("pipeline_status") or {}).get("step", "?")
        return True, f"long-form pipeline_status={step}"

    if shorts_state:
        if shorts_state.get("pipeline_status"):
            step = (shorts_state.get("pipeline_status") or {}).get("step", "?")
            return True, f"shorts pipeline_status={step}"
        if shorts_state.get("pending_upload"):
            return True, "shorts pending_upload"

    if os.path.isfile(checkpoint_path):
        try:
            import json
            with open(checkpoint_path, encoding="utf-8") as f:
                cp = json.load(f)
            if isinstance(cp, dict) and cp.get("date") == today and cp.get("steps"):
                return True, "active long-form checkpoint today"
        except (OSError, ValueError, TypeError):
            pass

    return False, ""


def maybe_daily_runtime_cleanup(
    *,
    now_utc=None,
    longform_state: dict | None = None,
    shorts_state: dict | None = None,
    last_cleanup_date: str | None = None,
) -> dict:
    """
    Once per local calendar day after DAILY_CLEANUP_HOUR, wipe cache/ + output/
    when no pipeline is busy. If busy, returns deferred (caller retries next tick).

    Returns a result dict with keys: ran, deferred, skipped, reason, stats?, date?
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    if not daily_cleanup_enabled():
        return {"ran": False, "deferred": False, "skipped": True, "reason": "disabled"}

    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    tz_name = daily_cleanup_timezone_name()
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
        tz_name = "Asia/Kolkata"

    now_local = now_utc.astimezone(tz)
    local_date = now_local.strftime("%Y-%m-%d")
    hour = daily_cleanup_hour()

    if last_cleanup_date == local_date:
        return {"ran": False, "deferred": False, "skipped": True, "reason": "already_done", "date": local_date}

    # Not yet cleanup hour today — wait (same-day only; no yesterday carry of "pending")
    if now_local.hour < hour:
        return {"ran": False, "deferred": False, "skipped": True, "reason": "before_hour", "date": local_date}

    busy, busy_reason = is_pipeline_busy(
        longform_state=longform_state,
        shorts_state=shorts_state,
        now_utc=now_utc,
    )
    if busy:
        return {
            "ran": False,
            "deferred": True,
            "skipped": False,
            "reason": busy_reason,
            "date": local_date,
            "timezone": tz_name,
        }

    stats = purge_runtime_dirs()
    return {
        "ran": True,
        "deferred": False,
        "skipped": False,
        "reason": "ok",
        "date": local_date,
        "timezone": tz_name,
        "hour": hour,
        "stats": stats,
    }
