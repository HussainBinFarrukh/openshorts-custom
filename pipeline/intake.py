"""Watchlist intake: new uploads on permissioned channels become OpenShorts jobs.

Guard rails, each one a cost that would otherwise grow with the channel:
- a channel is only read if it is on the watchlist with a permission note;
- only uploads published after the channel was added, and no older than
  ``PIPELINE_MAX_VIDEO_AGE_DAYS``, so adding a channel never pulls its back catalogue;
- ``PIPELINE_INTAKE_DAILY_LIMIT`` submissions per rolling 24 h across all channels;
- Shorts (<= 180 s), live/upcoming streams and non-public videos are skipped;
- only the first ``PIPELINE_MAX_SOURCE_MINUTES`` of a long source are clipped.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Awaitable, Callable, Iterable, Optional

from . import db
from .config import settings
from .youtube import YouTubeClient, YouTubeError

# submit(url, max_minutes) -> OpenShorts job id
Submitter = Callable[[str, int], Awaitable[str]]


# --------------------------------------------------------------------------- #
# Watchlist CRUD
# --------------------------------------------------------------------------- #
async def add_watch(channel_input: str, permission_note: str,
                    permission_granted_at: Optional[str] = None,
                    client: Optional[YouTubeClient] = None) -> dict:
    if not (permission_note or "").strip():
        raise ValueError("Record who granted permission (and how) before adding a channel.")
    async with (client or YouTubeClient()) as yt:
        ch = await yt.resolve_channel(channel_input)
    dup = db.query("SELECT id FROM watchlist WHERE channel_id = ?", (ch["channel_id"],))
    if dup:
        raise ValueError("That channel is already on the watchlist.")
    row = {
        "id": db.new_id(),
        "channel_input": channel_input.strip(),
        "channel_id": ch["channel_id"],
        "uploads_playlist_id": ch["uploads_playlist_id"],
        "title": ch["title"],
        "permission_note": permission_note.strip(),
        "permission_granted_at": permission_granted_at,
        "added_at": db.iso(),
        "active": 1,
    }
    db.insert("watchlist", row)
    return db.get("watchlist", row["id"])


def list_watches() -> list[dict]:
    return db.query("SELECT * FROM watchlist ORDER BY added_at DESC")


def set_active(watch_id: str, active: bool) -> None:
    db.update("watchlist", watch_id, {"active": 1 if active else 0})


def remove_watch(watch_id: str) -> None:
    db.execute("DELETE FROM watchlist WHERE id = ?", (watch_id,))


# --------------------------------------------------------------------------- #
# Selection (pure)
# --------------------------------------------------------------------------- #
def classify(video: dict, added_at: datetime, now: datetime,
             max_age: timedelta, shorts_max_s: float) -> Optional[str]:
    """None if the video should be clipped, else the reason to skip it."""
    published = db.parse_iso(video.get("published_at"))
    if not published or published < added_at:
        return "before_watch"
    if now - published > max_age:
        return "too_old"
    if video.get("live") in ("live", "upcoming"):
        return "live"
    if video.get("privacy") not in (None, "public"):
        return "not_public"
    dur = video.get("duration_s")
    if dur is None:
        return "processing"
    if dur <= shorts_max_s:
        return "short_form"
    return None


def pick_new(videos: Iterable[dict], seen: set, added_at: datetime, now: datetime,
             max_age: timedelta, shorts_max_s: float) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Split unseen videos into (to clip, oldest first) and (skipped, reason)."""
    take, skipped = [], []
    for v in videos:
        if v["video_id"] in seen:
            continue
        reason = classify(v, added_at, now, max_age, shorts_max_s)
        if reason == "before_watch":
            continue            # never record the back catalogue
        if reason == "processing":
            continue            # look again next tick
        (skipped.append((v, reason)) if reason else take.append(v))
    take.sort(key=lambda v: v.get("published_at") or "")
    return take, skipped


def submitted_last_24h(now: datetime) -> int:
    since = db.iso(now - timedelta(hours=24))
    rows = db.query(
        "SELECT COUNT(*) AS n FROM source_videos WHERE openshorts_job_id IS NOT NULL "
        "AND created_at >= ?", (since,))
    return int(rows[0]["n"])


# --------------------------------------------------------------------------- #
# Polling
# --------------------------------------------------------------------------- #
async def poll_once(submit: Submitter, client: Optional[YouTubeClient] = None,
                    now: Optional[datetime] = None) -> dict:
    s = settings()
    now = now or db.utcnow()
    summary = {"checked": 0, "submitted": 0, "skipped": 0, "errors": 0}
    watches = db.query("SELECT * FROM watchlist WHERE active = 1")
    if not watches or not s.yt_api_key:
        return summary

    async with (client or YouTubeClient()) as yt:
        for w in watches:
            summary["checked"] += 1
            try:
                videos = await yt.latest_uploads(w["uploads_playlist_id"])
            except YouTubeError as e:
                db.update("watchlist", w["id"], {"last_checked_at": db.iso(now), "last_error": str(e)})
                summary["errors"] += 1
                continue
            ids = [v["video_id"] for v in videos]
            seen = {r["youtube_video_id"] for r in db.query(
                f"SELECT youtube_video_id FROM source_videos WHERE youtube_video_id IN "
                f"({','.join('?' for _ in ids) or 'NULL'})", ids)}
            take, skipped = pick_new(
                videos, seen, db.parse_iso(w["added_at"]), now,
                timedelta(days=s.max_video_age_days), s.shorts_max_seconds)
            for v, reason in skipped:
                _record_source(w["id"], v, "skipped", skip_reason=reason, now=now)
                summary["skipped"] += 1
            for v in take:
                if submitted_last_24h(now) >= s.intake_daily_limit:
                    break       # stays unseen; picked up on a later tick if still young
                row = _record_source(w["id"], v, "queued", now=now)
                try:
                    job_id = await submit(v["url"], s.max_source_minutes)
                except Exception as e:  # noqa: BLE001 - surface any submit failure on the row
                    db.update("source_videos", row["id"], {
                        "status": "failed", "error": str(e)[:500], "updated_at": db.iso(now)})
                    summary["errors"] += 1
                    continue
                db.update("source_videos", row["id"], {
                    "status": "processing", "openshorts_job_id": job_id, "updated_at": db.iso(now)})
                summary["submitted"] += 1
            db.update("watchlist", w["id"], {"last_checked_at": db.iso(now), "last_error": None})
    return summary


async def submit_url(url: str, submit: Submitter, title: Optional[str] = None) -> dict:
    """Manual intake of one video (still recorded as a source)."""
    s = settings()
    now = db.utcnow()
    vid = _video_id(url)
    if vid and db.query("SELECT id FROM source_videos WHERE youtube_video_id = ?", (vid,)):
        raise ValueError("That video is already in the pipeline.")
    row = _record_source(None, {"video_id": vid, "url": url, "title": title}, "queued", now=now)
    job_id = await submit(url, s.max_source_minutes)
    db.update("source_videos", row["id"], {
        "status": "processing", "openshorts_job_id": job_id, "updated_at": db.iso(now)})
    return db.get("source_videos", row["id"])


def _record_source(watch_id, v: dict, status: str, skip_reason: Optional[str] = None,
                   now: Optional[datetime] = None) -> dict:
    row = {
        "id": db.new_id(),
        "watch_id": watch_id,
        "youtube_video_id": v.get("video_id"),
        "url": v["url"],
        "title": v.get("title"),
        "published_at": v.get("published_at"),
        "duration_s": v.get("duration_s"),
        "status": status,
        "skip_reason": skip_reason,
        "created_at": db.iso(now),
        "updated_at": db.iso(now),
    }
    db.insert("source_videos", row)
    return row


def _video_id(url: str) -> Optional[str]:
    import re
    m = re.search(r"(?:v=|youtu\.be/|shorts/|live/)([\w\-]{11})", url or "")
    return m.group(1) if m else None
