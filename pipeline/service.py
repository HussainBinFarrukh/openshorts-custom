"""Background loops and the glue between the pipeline and app.py.

Self-host only: cloud mode (``BILLING_ENABLED``) has its own Autopilot under
``cloud/`` and never starts these loops.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Optional

import httpx

from . import analytics, clips, commentary, db, intake, scheduler
from .config import settings

TICK_SECONDS = 60
ANALYTICS_EVERY = 15 * 60

_app = None
_output_root = "output"
_is_active: Callable[[], bool] = lambda: True
_tasks: set = set()
_state = {"last_intake": None, "last_intake_result": None, "last_publish_result": None,
          "last_analytics": None, "last_error": None}


def status() -> dict:
    return dict(_state)


async def submit_to_openshorts(url: str, max_minutes: int) -> str:
    """Submit a URL to this server's own /api/process, in-process (no network hop).

    Going through the endpoint instead of calling internals keeps every guard it
    applies (source validation, quality probe, queueing) in one place.
    """
    if _app is None:
        raise RuntimeError("Pipeline is not started.")
    transport = httpx.ASGITransport(app=_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://pipeline.local",
                                 timeout=300) as client:
        resp = await client.post("/api/process", json={
            "url": url, "acknowledged": True, "max_minutes": max_minutes,
            "output_format": "vertical"})
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = resp.text[:300]
        raise RuntimeError(f"OpenShorts refused the video ({resp.status_code}): {detail}")
    job_id = resp.json().get("job_id")
    if not job_id:
        raise RuntimeError("OpenShorts did not return a job id.")
    return job_id


async def on_job_finished(job_id: str, job: dict) -> None:
    """Called from app.py's job wrapper for every job; ours are picked out by id."""
    try:
        await asyncio.to_thread(clips.on_job_finished, job_id, job, _output_root)
    except Exception as e:  # noqa: BLE001 - never break the host's job wrapper
        _state["last_error"] = f"register clips for {job_id}: {e}"
        print(f"⚠️ Pipeline could not register clips for {job_id}: {e}")


async def _loop() -> None:
    since_intake = None
    since_analytics = 0.0
    while True:
        await asyncio.sleep(TICK_SECONDS)
        if not _is_active():
            continue
        s = settings()
        try:
            now = db.utcnow()
            if since_intake is None or (now - since_intake).total_seconds() >= s.intake_every_minutes * 60:
                since_intake = now
                _state["last_intake"] = db.iso(now)
                _state["last_intake_result"] = await intake.poll_once(submit_to_openshorts)
            _state["last_publish_result"] = await scheduler.publish_due()
            since_analytics += TICK_SECONDS
            if since_analytics >= ANALYTICS_EVERY:
                since_analytics = 0.0
                _state["last_analytics"] = await analytics.pull_due()
            await asyncio.to_thread(commentary.compose_pending)
        except Exception as e:  # noqa: BLE001 - keep the loop alive, show the error
            _state["last_error"] = str(e)[:500]
            print(f"⚠️ Pipeline tick failed: {e}")


def start(app, output_root: str = "output", is_active: Optional[Callable[[], bool]] = None) -> None:
    global _app, _output_root, _is_active
    _app = app
    _output_root = output_root
    if is_active is not None:
        _is_active = is_active
    db.init()
    if not settings().enabled:
        print("ℹ️ Pipeline loops disabled (PIPELINE_ENABLED=0); API still available.")
        return
    task = asyncio.create_task(_loop())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    print("✅ Pipeline started (intake, compose, publish, analytics).")
