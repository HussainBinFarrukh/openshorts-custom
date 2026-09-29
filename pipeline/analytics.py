"""Performance pulls at 24 h, 72 h and 7 days after a clip is published.

Each checkpoint is one row per clip (``metrics``), joined to the clip, its
source and its reaction by id, so later analysis can ask which sources,
layouts, hooks and lengths hold viewers.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from . import db
from .youtube import YouTubeClient, YouTubeError

CHECKPOINTS = (("24h", timedelta(hours=24)), ("72h", timedelta(hours=72)),
               ("7d", timedelta(days=7)))


def due(now: datetime) -> list[tuple[dict, str]]:
    out = []
    for clip in db.query("SELECT * FROM clips WHERE status = 'published' "
                         "AND youtube_video_id IS NOT NULL"):
        published = db.parse_iso(clip.get("published_at"))
        if not published:
            continue
        pulled = {r["checkpoint"] for r in db.query(
            "SELECT checkpoint FROM metrics WHERE clip_id = ?", (clip["id"],))}
        for name, delta in CHECKPOINTS:
            if name not in pulled and now >= published + delta:
                out.append((clip, name))
    return out


async def pull_due(client: Optional[YouTubeClient] = None,
                   now: Optional[datetime] = None) -> int:
    now = now or db.utcnow()
    todo = due(now)
    if not todo:
        return 0
    n = 0
    async with (client or YouTubeClient()) as yt:
        for clip, checkpoint in todo:
            try:
                stats = await yt.video_stats(clip["youtube_video_id"])
                extra = await yt.video_analytics(
                    clip["youtube_video_id"], db.parse_iso(clip["published_at"]))
            except YouTubeError as e:
                if e.reauth:
                    break
                continue
            db.insert("metrics", {
                "id": db.new_id(), "clip_id": clip["id"], "checkpoint": checkpoint,
                "pulled_at": db.iso(now),
                "views": stats.get("views"), "likes": stats.get("likes"),
                "comments": stats.get("comments"),
                "avg_view_duration_s": extra.get("avg_view_duration_s"),
                "avg_view_pct": extra.get("avg_view_pct"),
                "subscribers_gained": extra.get("subscribers_gained"),
                "raw": {"stats": stats, "analytics": extra},
            })
            n += 1
    return n


def performance() -> list[dict]:
    """Latest checkpoint per published clip, with the features worth comparing."""
    return db.query("""
        SELECT c.id, c.title, c.layout, c.duration_s, c.hook_text, c.youtube_video_id,
               c.published_at, s.title AS source_title, w.title AS channel_title,
               seg.speech_seconds,
               m.checkpoint, m.views, m.likes, m.comments, m.avg_view_duration_s,
               m.avg_view_pct, m.subscribers_gained
        FROM clips c
        LEFT JOIN source_videos s ON s.id = c.source_video_id
        LEFT JOIN watchlist w ON w.id = s.watch_id
        LEFT JOIN reaction_segments seg ON seg.id = c.reaction_segment_id
        LEFT JOIN metrics m ON m.id = (
            SELECT id FROM metrics WHERE clip_id = c.id
            ORDER BY CASE checkpoint WHEN '7d' THEN 3 WHEN '72h' THEN 2 ELSE 1 END DESC
            LIMIT 1)
        WHERE c.status = 'published'
        ORDER BY c.published_at DESC
    """)
