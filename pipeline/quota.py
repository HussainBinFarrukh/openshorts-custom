"""YouTube Data API quota accounting.

The Data API gives each Google Cloud project a daily unit budget that resets at
midnight Pacific time. We record every call we make so the scheduler can refuse
an upload that would overrun the budget instead of failing mid-publish.

Costs used here (Data API v3 quota calculator): list calls 1 unit,
videos.insert ~1,600 (configurable, PIPELINE_YT_UPLOAD_COST).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from . import db
from .config import settings

PACIFIC = ZoneInfo("America/Los_Angeles")

LIST_COST = 1


def quota_day(now: Optional[datetime] = None) -> str:
    return (now or db.utcnow()).astimezone(PACIFIC).date().isoformat()


def record(units: int, op: str, now: Optional[datetime] = None) -> None:
    db.insert("quota_ledger", {
        "day": quota_day(now), "units": int(units), "op": op, "at": db.iso(now)})


def used_today(now: Optional[datetime] = None) -> int:
    rows = db.query("SELECT COALESCE(SUM(units), 0) AS used FROM quota_ledger WHERE day = ?",
                    (quota_day(now),))
    return int(rows[0]["used"]) if rows else 0


def remaining(now: Optional[datetime] = None) -> int:
    return settings().yt_daily_quota - used_today(now)


def can_spend(units: int, now: Optional[datetime] = None) -> bool:
    return remaining(now) >= units


def summary(now: Optional[datetime] = None) -> dict:
    s = settings()
    used = used_today(now)
    return {
        "day": quota_day(now),
        "used": used,
        "limit": s.yt_daily_quota,
        "remaining": s.yt_daily_quota - used,
        "upload_cost": s.yt_upload_cost,
        "uploads_left_today": max(0, (s.yt_daily_quota - used) // max(1, s.yt_upload_cost)),
    }
