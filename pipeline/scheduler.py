"""Approval, paced scheduling and publishing.

Approving a clip is the only human step; it immediately gets the next free
slot that respects the daily cap, the minimum gap and the publish window. A
background tick uploads clips whose slot has arrived, if the day's Data API
quota still covers an upload.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from . import clips, db, quota
from .config import Settings, settings
from .youtube import YouTubeClient, YouTubeError

LEAD = timedelta(minutes=5)
SEARCH_DAYS = 60


def plan_slot(now: datetime, taken: list[datetime], s: Settings) -> datetime:
    """Earliest time >= now + LEAD inside the window, under the daily cap, and at
    least ``publish_min_gap_minutes`` from every taken slot."""
    if s.publish_max_per_day <= 0:
        raise ValueError("Publishing is paused (PIPELINE_PUBLISH_MAX_PER_DAY=0).")
    tz = ZoneInfo(s.timezone)
    gap = timedelta(minutes=s.publish_min_gap_minutes)
    win_start, win_end = s.publish_window
    cand = (now + LEAD).astimezone(tz).replace(second=0, microsecond=0)
    limit = cand + timedelta(days=SEARCH_DAYS)
    taken_local = sorted(t.astimezone(tz) for t in taken)
    while cand < limit:
        day_start = cand.replace(hour=win_start.hour, minute=win_start.minute)
        day_end = cand.replace(hour=win_end.hour, minute=win_end.minute)
        if cand < day_start:
            cand = day_start
        if cand > day_end:
            cand = (cand + timedelta(days=1)).replace(
                hour=win_start.hour, minute=win_start.minute)
            continue
        same_day = [t for t in taken_local if t.date() == cand.date()]
        if len(same_day) >= s.publish_max_per_day:
            cand = (cand + timedelta(days=1)).replace(
                hour=win_start.hour, minute=win_start.minute)
            continue
        clash = [t for t in taken_local if abs(t - cand) < gap]
        if clash:
            cand = max(clash) + gap
            continue
        return cand.astimezone(ZoneInfo("UTC"))
    raise ValueError("No publish slot found in the next 60 days.")


def _taken_slots() -> list[datetime]:
    rows = db.query(
        "SELECT scheduled_for, published_at FROM clips WHERE status IN ('scheduled', 'published')")
    out = []
    for r in rows:
        dt = db.parse_iso(r.get("published_at") or r.get("scheduled_for"))
        if dt:
            out.append(dt)
    return out


def approve(clip_id: str, reviewer: str, now: Optional[datetime] = None) -> dict:
    clip = db.get("clips", clip_id)
    if not clip:
        raise clips.TransitionError("Clip not found.")
    if clip["status"] != "pending_review":
        raise clips.TransitionError("Only clips in review can be approved.")
    if not (clip.get("qa_report") or {}).get("passed"):
        raise clips.TransitionError("This clip has not passed QA.")
    if not (reviewer or "").strip():
        raise clips.TransitionError("Record who is approving.")
    now = now or db.utcnow()
    clips.transition(clip_id, "approved", approved_by=reviewer.strip()[:80], approved_at=db.iso(now))
    return schedule(clip_id, now)


def reject(clip_id: str, note: str = "") -> dict:
    return clips.transition(clip_id, "rejected", review_note=(note or "")[:500])


def send_back(clip_id: str, note: str = "") -> dict:
    """Back to the shortlist for a new reaction."""
    return clips.transition(clip_id, "shortlisted", review_note=(note or "")[:500],
                            reaction_segment_id=None, composed_path=None, qa_report=None)


def schedule(clip_id: str, now: Optional[datetime] = None) -> dict:
    clip = db.get("clips", clip_id)
    if not clip or clip["status"] not in ("approved", "publish_failed"):
        raise clips.TransitionError("Only approved clips can be scheduled.")
    slot = plan_slot(now or db.utcnow(), _taken_slots(), settings())
    return clips.transition(clip_id, "scheduled", scheduled_for=db.iso(slot), publish_error=None)


def unschedule(clip_id: str) -> dict:
    return clips.transition(clip_id, "approved", scheduled_for=None)


def upcoming() -> list[dict]:
    return db.query("SELECT * FROM clips WHERE status = 'scheduled' ORDER BY scheduled_for")


async def publish_due(client: Optional[YouTubeClient] = None,
                      now: Optional[datetime] = None) -> dict:
    s = settings()
    now = now or db.utcnow()
    result = {"published": 0, "failed": 0, "waiting_quota": 0}
    due = db.query("SELECT * FROM clips WHERE status = 'scheduled' AND scheduled_for <= ? "
                   "ORDER BY scheduled_for", (db.iso(now),))
    if not due:
        return result
    async with (client or YouTubeClient()) as yt:
        for clip in due:
            if not quota.can_spend(s.yt_upload_cost, now):
                result["waiting_quota"] += 1
                continue
            path = clip.get("composed_path")
            if not (path and _exists(path)):
                clips.transition(clip["id"], "publish_failed",
                                 publish_error="The composed video file is missing.")
                result["failed"] += 1
                continue
            try:
                video_id = await yt.upload(
                    path, clip["title"], clip.get("description") or "",
                    clip.get("tags") or [], s.privacy, s.yt_category_id)
            except YouTubeError as e:
                if e.reauth:
                    db.update("clips", clip["id"], {"publish_error": str(e)})
                    break      # every upload will fail the same way until reconnect
                clips.transition(clip["id"], "publish_failed", publish_error=str(e)[:500])
                result["failed"] += 1
                continue
            clips.transition(clip["id"], "published", youtube_video_id=video_id,
                             published_at=db.iso(db.utcnow()), publish_error=None)
            result["published"] += 1
    return result


def _exists(path: str) -> bool:
    import os
    return os.path.isfile(path)
