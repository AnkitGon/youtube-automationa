"""
Simple Telegram notifications via direct HTTP — no async needed.
Used by agent.py to push status updates.
"""
import html
import os
from datetime import datetime
import requests


def _esc(value) -> str:
    """Escape testo dinamico per parse_mode=HTML (titoli/errori con < & >)."""
    return html.escape(str(value), quote=True)

def _send(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def _send_photo(image_path: str, caption: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        with open(image_path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": f},
                timeout=20,
            )
    except Exception:
        pass


def notify_start(topic: str) -> None:
    _send(f"🎬 <b>Nuovo video in produzione</b>\n\n📌 Topic: <i>{_esc(topic)}</i>\n\nInizio pipeline...")


def notify_step(step: str, detail: str = "") -> None:
    icons = {
        "audio": "🎙️",
        "clips": "🎞️",
        "rendering": "⚙️",
        "thumbnail": "🖼️",
        "upload": "📤",
        "strategy": "🧠",
    }
    icon = icons.get(step, "▶️")
    msg = f"{icon} <b>{step.capitalize()}</b>"
    if detail:
        msg += f"\n{detail}"
    _send(msg)


def notify_done(
    title: str,
    video_id: str,
    publish_time: str,
    thumb_path: str,
    schedule_decision: dict | None = None,
) -> None:
    if schedule_decision:
        from moduli.publish_scheduler import ScheduleDecision, format_telegram_schedule
        try:
            dec = ScheduleDecision(
                publish_at_utc=datetime.fromisoformat(
                    schedule_decision["publish_at_utc"].replace("Z", "+00:00")
                ),
                audience_timezone=schedule_decision.get("audience_timezone", ""),
                local_publish_label=schedule_decision.get("local_publish_label", publish_time),
                peak_day=schedule_decision.get("peak_day"),
                peak_hour_local=schedule_decision.get("peak_hour_local"),
                confidence=schedule_decision.get("confidence", "LOW"),
                fallback_used=bool(schedule_decision.get("fallback_used")),
                analytics_available=bool(schedule_decision.get("analytics_available")),
                source=schedule_decision.get("source", "fallback"),
                reason=schedule_decision.get("reason", ""),
                audience_basis=schedule_decision.get("audience_basis", ""),
                utc_label=schedule_decision.get("utc_label", ""),
                youtube_publish_at=schedule_decision.get("youtube_publish_at", ""),
            )
            schedule_block = format_telegram_schedule(dec)
        except Exception:
            schedule_block = f"⏰ Publish: {_esc(publish_time)}"
    else:
        schedule_block = f"⏰ Publish: {_esc(publish_time)}"

    caption = (
        f"✅ <b>Video scheduled!</b>\n\n"
        f"📹 <b>{_esc(title)}</b>\n"
        f"🔗 https://youtu.be/{video_id}\n\n"
        f"{schedule_block}"
    )
    if thumb_path and os.path.exists(thumb_path):
        _send_photo(thumb_path, caption)
    else:
        _send(caption)


def notify_error(error: str) -> None:
    _send(f"❌ <b>Errore pipeline</b>\n\n<code>{_esc(error[:500])}</code>")


def notify_analytics(stats: list) -> None:
    if not stats:
        _send("📊 <b>Recap analytics</b>\n\nNessun video ancora.")
        return
    lines = ["📊 <b>Recap ultimi video</b>\n"]
    for v in stats:
        retention = int(v.get("avg_view_duration_seconds", 0) / max(v.get("duration_seconds", 480), 1) * 100)
        lines.append(
            f"▪️ <i>{_esc(v['title'][:40])}</i>\n"
            f"   👁 {v['views']} views | ❤️ {v['likes']} likes | 🔁 {retention}% retention\n"
        )
    _send("\n".join(lines))


def notify_shorts_done(title: str, video_id: str, schedule_decision: dict | None = None) -> None:
    schedule_block = ""
    if schedule_decision:
        local = schedule_decision.get("local_publish_label", "")
        yt_at = schedule_decision.get("youtube_publish_at", "")
        conf = schedule_decision.get("confidence", "")
        schedule_block = f"📅 {local}\n🕐 UTC: {yt_at}\n📊 Confidence: {conf}"
    _send(
        f"📱 <b>Short scheduled!</b>\n\n"
        f"📹 <b>{_esc(title)}</b>\n"
        f"🔗 https://youtube.com/shorts/{video_id}\n\n"
        f"{schedule_block}"
    )


def notify_shorts_batch_summary(successes: int, failures: int) -> None:
    icon = "✅" if failures == 0 else "⚠️"
    _send(
        f"{icon} <b>Shorts batch complete</b>\n\n"
        f"Published: {successes}\n"
        f"Failed: {failures}"
    )
