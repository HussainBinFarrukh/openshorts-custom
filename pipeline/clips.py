"""Clips: taking OpenShorts output into the pipeline, and the clip state machine.

OpenShorts deletes a job's directory after ``JOB_RETENTION_SECONDS`` (24 h on
self-host), so each rendered clip is copied into the pipeline's own storage the
moment its job finishes.
"""
from __future__ import annotations

import os
import shutil
from typing import Optional

from . import db
from .config import settings

# state -> states it may move to
TRANSITIONS = {
    "draft": {"shortlisted", "rejected"},
    "shortlisted": {"awaiting_reaction", "draft", "rejected"},
    "awaiting_reaction": {"composing", "shortlisted", "rejected"},
    "composing": {"qa_failed", "pending_review", "awaiting_reaction"},
    "qa_failed": {"composing", "awaiting_reaction", "shortlisted", "rejected"},
    "pending_review": {"approved", "rejected", "shortlisted", "composing"},
    "approved": {"scheduled", "pending_review"},
    "scheduled": {"published", "publish_failed", "approved"},
    "publish_failed": {"scheduled", "approved"},
    "published": set(),
    "rejected": {"draft"},
}


class TransitionError(ValueError):
    pass


def transition(clip_id: str, to: str, **fields) -> dict:
    clip = db.get("clips", clip_id)
    if not clip:
        raise TransitionError("Clip not found.")
    if to not in TRANSITIONS.get(clip["status"], set()):
        raise TransitionError(f"A {clip['status']} clip cannot become {to}.")
    db.update("clips", clip_id, {"status": to, "updated_at": db.iso(), **fields})
    return db.get("clips", clip_id)


def register_job_clips(job_id: str, job: dict, output_root: str,
                       source_video_id: Optional[str] = None) -> list[dict]:
    """Copy a finished job's clips into pipeline storage as ``draft`` rows.

    Idempotent: a clip already registered for (job, index) is left alone.
    """
    s = settings()
    clips = ((job or {}).get("result") or {}).get("clips") or []
    created = []
    for index, clip in enumerate(clips):
        rel = clip.get("video_url") or ""
        prefix = f"/videos/{job_id}/"
        if not rel.startswith(prefix):
            continue
        filename = os.path.basename(rel[len(prefix):])
        src = os.path.join(output_root, job_id, filename)
        if not os.path.isfile(src):
            continue
        if db.query("SELECT id FROM clips WHERE openshorts_job_id = ? AND clip_index = ?",
                    (job_id, index)):
            continue
        clip_id = db.new_id()
        dest = s.path("clips", f"{clip_id}.mp4")
        shutil.copy2(src, dest)
        start, end = _float(clip.get("start")), _float(clip.get("end"))
        row = {
            "id": clip_id,
            "source_video_id": source_video_id,
            "openshorts_job_id": job_id,
            "clip_index": index,
            "status": "draft",
            "title": (clip.get("video_title_for_youtube_short") or clip.get("title") or "")[:100],
            "description": clip.get("video_description_for_instagram")
            or clip.get("video_description_for_tiktok") or "",
            "tags": [],
            "hook_text": clip.get("viral_hook_text"),
            "start_s": start,
            "end_s": end,
            "duration_s": (end - start) if start is not None and end is not None else None,
            "raw_path": dest,
            "meta_json": {k: v for k, v in clip.items() if isinstance(v, (str, int, float, bool))},
            "created_at": db.iso(),
            "updated_at": db.iso(),
        }
        db.insert("clips", row)
        created.append(db.get("clips", clip_id))
    return created


def on_job_finished(job_id: str, job: dict, output_root: str) -> list[dict]:
    """Hook called by app.py when any OpenShorts job ends. Ignores jobs we did not submit."""
    src = db.query("SELECT * FROM source_videos WHERE openshorts_job_id = ?", (job_id,))
    if not src:
        return []
    source = src[0]
    if (job or {}).get("status") != "completed":
        db.update("source_videos", source["id"], {
            "status": "failed", "error": _last_log(job), "updated_at": db.iso()})
        return []
    created = register_job_clips(job_id, job, output_root, source["id"])
    # Judge by all clips of the job, not just new ones: the hook may fire twice.
    has_clips = bool(db.query("SELECT id FROM clips WHERE openshorts_job_id = ? LIMIT 1", (job_id,)))
    db.update("source_videos", source["id"], {
        "status": "completed" if has_clips else "failed",
        "error": None if has_clips else "No clips were produced.",
        "updated_at": db.iso()})
    return created


def import_job(job_id: str, job: dict, output_root: str) -> list[dict]:
    """Bring a job run by hand in the Clip Generator into the pipeline."""
    existing = db.query("SELECT id FROM source_videos WHERE openshorts_job_id = ?", (job_id,))
    if existing:
        source_id = existing[0]["id"]
    else:
        source_id = db.new_id()
        db.insert("source_videos", {
            "id": source_id, "url": (job or {}).get("url") or f"job:{job_id}",
            "title": (job or {}).get("title"), "status": "completed",
            "openshorts_job_id": job_id, "created_at": db.iso(), "updated_at": db.iso()})
    return register_job_clips(job_id, job, output_root, source_id)


def list_clips(statuses: Optional[list[str]] = None, limit: int = 200) -> list[dict]:
    if statuses:
        marks = ",".join("?" for _ in statuses)
        return db.query(
            f"SELECT * FROM clips WHERE status IN ({marks}) ORDER BY created_at DESC LIMIT ?",
            [*statuses, limit])
    return db.query("SELECT * FROM clips ORDER BY created_at DESC LIMIT ?", (limit,))


def update_metadata(clip_id: str, title: Optional[str] = None, description: Optional[str] = None,
                    tags: Optional[list[str]] = None, layout: Optional[str] = None) -> dict:
    clip = db.get("clips", clip_id)
    if not clip:
        raise TransitionError("Clip not found.")
    if clip["status"] in ("scheduled", "published"):
        raise TransitionError("Unschedule the clip before editing it.")
    values = {}
    if title is not None:
        title = title.strip()
        if not title or len(title) > 100:
            raise TransitionError("Titles must be 1-100 characters.")
        values["title"] = title
    if description is not None:
        values["description"] = description[:5000]
    if tags is not None:
        values["tags"] = [t.strip() for t in tags if t and t.strip()][:30]
    if layout is not None:
        if layout not in ("stacked", "pip"):
            raise TransitionError("Layout must be stacked or pip.")
        values["layout"] = layout
    if values:
        values["updated_at"] = db.iso()
        db.update("clips", clip_id, values)
    return db.get("clips", clip_id)


def _float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _last_log(job) -> str:
    logs = list((job or {}).get("logs") or [])
    return (str(logs[-1]) if logs else "OpenShorts job failed.")[:500]
