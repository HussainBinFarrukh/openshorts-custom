"""HTTP API for the Pipeline dashboard tab: /api/pipeline/*."""
from __future__ import annotations

import asyncio
import os
import secrets
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import analytics, clips, commentary, db, intake, media, quota, scheduler, service, youtube
from .config import settings

MAX_REACTION_BYTES = 8 * 1024 ** 3
REACTION_TYPES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def require_token(request: Request) -> None:
    """Optional shared secret: set PIPELINE_ADMIN_TOKEN if the port is reachable by others."""
    token = settings().admin_token
    if not token:
        return
    sent = request.headers.get("X-Pipeline-Token") or request.query_params.get("token") or ""
    if not secrets.compare_digest(sent, token):
        raise HTTPException(401, "Pipeline token required.")


router = APIRouter(prefix="/api/pipeline", dependencies=[Depends(require_token)])


def _bad(e: Exception, code: int = 400):
    raise HTTPException(code, str(e))


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
@router.get("/overview")
async def overview():
    counts = {r["status"]: r["n"] for r in db.query(
        "SELECT status, COUNT(*) AS n FROM clips GROUP BY status")}
    return {
        "counts": counts,
        "quota": quota.summary(),
        "youtube": youtube.connection_status(),
        "loops": service.status(),
        "settings": _settings_view(),
    }


def _settings_view() -> dict:
    s = settings()
    return {
        "timezone": s.timezone,
        "intake_daily_limit": s.intake_daily_limit,
        "publish_max_per_day": s.publish_max_per_day,
        "publish_min_gap_minutes": s.publish_min_gap_minutes,
        "publish_window": [s.publish_window[0].strftime("%H:%M"), s.publish_window[1].strftime("%H:%M")],
        "min_commentary_seconds": s.min_commentary_seconds,
        "reaction_tail_seconds": s.reaction_tail_seconds,
        "privacy": s.privacy,
    }


# --------------------------------------------------------------------------- #
# Watchlist + sources
# --------------------------------------------------------------------------- #
class WatchIn(BaseModel):
    channel: str
    permission_note: str
    permission_granted_at: Optional[str] = None


@router.get("/watchlist")
async def get_watchlist():
    return {"watches": intake.list_watches()}


@router.post("/watchlist")
async def add_watch(body: WatchIn):
    try:
        return await intake.add_watch(body.channel, body.permission_note, body.permission_granted_at)
    except (ValueError, youtube.YouTubeError) as e:
        _bad(e)


@router.patch("/watchlist/{watch_id}")
async def toggle_watch(watch_id: str, body: dict):
    intake.set_active(watch_id, bool(body.get("active")))
    return {"ok": True}


@router.delete("/watchlist/{watch_id}")
async def delete_watch(watch_id: str):
    intake.remove_watch(watch_id)
    return {"ok": True}


@router.post("/intake/run")
async def run_intake():
    return await intake.poll_once(service.submit_to_openshorts)


class UrlIn(BaseModel):
    url: str
    title: Optional[str] = None


@router.post("/sources")
async def add_source(body: UrlIn):
    try:
        return await intake.submit_url(body.url, service.submit_to_openshorts, body.title)
    except (ValueError, RuntimeError) as e:
        _bad(e)


@router.get("/sources")
async def list_sources(limit: int = 100):
    return {"sources": db.query(
        "SELECT * FROM source_videos ORDER BY created_at DESC LIMIT ?", (min(limit, 500),))}


class JobIn(BaseModel):
    job_id: str


@router.post("/import-job")
async def import_job(body: JobIn, request: Request):
    """Pull clips from a job run by hand in the Clip Generator into the pipeline."""
    jobs = getattr(request.app.state, "pipeline_jobs", None)
    job = jobs.get(body.job_id) if jobs is not None else None
    if not job or job.get("status") != "completed":
        raise HTTPException(404, "No completed job with that id on this server.")
    created = await asyncio.to_thread(clips.import_job, body.job_id, job, service._output_root)
    return {"created": created}


# --------------------------------------------------------------------------- #
# Clips + review
# --------------------------------------------------------------------------- #
@router.get("/clips")
async def list_clips(status: Optional[str] = None):
    statuses = [x for x in (status or "").split(",") if x] or None
    return {"clips": clips.list_clips(statuses)}


@router.get("/clips/{clip_id}")
async def get_clip(clip_id: str):
    clip = db.get("clips", clip_id)
    if not clip:
        raise HTTPException(404, "Clip not found.")
    clip["segment"] = commentary.segment_for(clip_id)
    clip["metrics"] = db.query("SELECT * FROM metrics WHERE clip_id = ? ORDER BY pulled_at", (clip_id,))
    return clip


class MetaIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    layout: Optional[str] = None


@router.patch("/clips/{clip_id}")
async def edit_clip(clip_id: str, body: MetaIn):
    try:
        return clips.update_metadata(clip_id, body.title, body.description, body.tags, body.layout)
    except clips.TransitionError as e:
        _bad(e)


class ActionIn(BaseModel):
    action: str
    reviewer: Optional[str] = None
    note: Optional[str] = None


@router.post("/clips/{clip_id}/action")
async def clip_action(clip_id: str, body: ActionIn):
    try:
        if body.action == "shortlist":
            return clips.transition(clip_id, "shortlisted")
        if body.action == "unshortlist":
            return clips.transition(clip_id, "draft")
        if body.action == "restore":
            return clips.transition(clip_id, "draft")
        if body.action == "approve":
            return scheduler.approve(clip_id, body.reviewer or "")
        if body.action == "reject":
            return scheduler.reject(clip_id, body.note or "")
        if body.action == "send_back":
            return scheduler.send_back(clip_id, body.note or "")
        if body.action == "unschedule":
            return scheduler.unschedule(clip_id)
        if body.action == "reschedule":
            return scheduler.schedule(clip_id)
        if body.action == "recompose":
            return await asyncio.to_thread(commentary.compose_clip, clip_id)
    except (clips.TransitionError, ValueError, media.MediaError) as e:
        _bad(e)
    raise HTTPException(400, f"Unknown action {body.action!r}.")


# --------------------------------------------------------------------------- #
# Commentary
# --------------------------------------------------------------------------- #
class SheetIn(BaseModel):
    clip_ids: list[str]


@router.post("/sheets")
async def create_sheet(body: SheetIn):
    if not body.clip_ids:
        raise HTTPException(400, "Pick at least one clip.")
    try:
        return await asyncio.to_thread(commentary.build_sheet, body.clip_ids)
    except (clips.TransitionError, media.MediaError) as e:
        _bad(e)


@router.get("/sheets")
async def list_sheets():
    return {"sheets": commentary.list_sheets()}


@router.post("/sheets/{sheet_id}/reaction")
async def upload_reaction(sheet_id: str, file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in REACTION_TYPES:
        raise HTTPException(400, f"Upload one of: {', '.join(sorted(REACTION_TYPES))}.")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=settings().path("incoming"))
    size = 0
    try:
        while chunk := await file.read(4 * 1024 * 1024):
            size += len(chunk)
            if size > MAX_REACTION_BYTES:
                raise HTTPException(413, "Recording is larger than 8 GB.")
            tmp.write(chunk)
        tmp.close()
        result = await asyncio.to_thread(commentary.ingest_reaction, sheet_id, tmp.name)
    except (clips.TransitionError, media.MediaError) as e:
        _bad(e)
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
    asyncio.create_task(asyncio.to_thread(commentary.compose_pending))
    return result


class OffsetIn(BaseModel):
    manual_offset_ms: int


@router.post("/segments/{segment_id}/offset")
async def nudge_segment(segment_id: str, body: OffsetIn):
    try:
        seg = await asyncio.to_thread(commentary.adjust_segment, segment_id, body.manual_offset_ms)
        clip = await asyncio.to_thread(commentary.compose_clip, seg["clip_id"])
    except (clips.TransitionError, media.MediaError) as e:
        _bad(e)
    return {"segment": seg, "clip": clip}


# --------------------------------------------------------------------------- #
# Schedule, YouTube, performance
# --------------------------------------------------------------------------- #
@router.get("/schedule")
async def schedule_view():
    return {"upcoming": scheduler.upcoming(), "quota": quota.summary()}


@router.post("/publish/run")
async def run_publish():
    return await scheduler.publish_due()


@router.get("/performance")
async def performance():
    return {"rows": analytics.performance()}


@router.post("/analytics/run")
async def run_analytics():
    return {"pulled": await analytics.pull_due()}


@router.get("/youtube/connect")
async def youtube_connect():
    try:
        return {"url": youtube.YouTubeClient.auth_url()}
    except youtube.YouTubeError as e:
        _bad(e)


@router.post("/youtube/disconnect")
async def youtube_disconnect():
    youtube.disconnect()
    return youtube.connection_status()


# The OAuth redirect is opened by Google in the browser, so it cannot carry the
# admin token header; the random ``state`` stored at connect time protects it.
callback_router = APIRouter(prefix="/api/pipeline")


@callback_router.get("/youtube/callback", response_class=HTMLResponse)
async def youtube_callback(code: str = "", state: str = "", error: str = ""):
    if error:
        return HTMLResponse(f"<p>YouTube connection cancelled: {error}</p>", status_code=400)
    try:
        async with youtube.YouTubeClient() as yt:
            st = await yt.exchange_code(code, state)
    except youtube.YouTubeError as e:
        return HTMLResponse(f"<p>Could not connect YouTube: {e}</p>", status_code=400)
    name = st.get("channel_title") or "your channel"
    return HTMLResponse(f"<p>Connected {name}. You can close this tab and return to the Pipeline tab.</p>")


# --------------------------------------------------------------------------- #
# Media
# --------------------------------------------------------------------------- #
@router.get("/media/{kind}/{item_id}")
async def media_file(kind: str, item_id: str):
    if kind == "raw":
        row = db.get("clips", item_id)
        path = row and row.get("raw_path")
    elif kind == "composed":
        row = db.get("clips", item_id)
        path = row and row.get("composed_path")
    elif kind == "sheet":
        row = db.get("watch_sheets", item_id)
        path = row and row.get("path")
    else:
        raise HTTPException(404, "Unknown media kind.")
    root = os.path.realpath(settings().data_dir)
    if not path or not os.path.realpath(path).startswith(root + os.sep) or not os.path.isfile(path):
        raise HTTPException(404, "File not found.")
    return FileResponse(path, media_type="video/mp4")
