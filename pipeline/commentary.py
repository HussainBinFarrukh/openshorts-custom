"""Commentary: watch sheets, reaction sessions, alignment, composition and QA.

All functions here are synchronous and CPU/ffmpeg bound; the router runs them
in a worker thread so the event loop stays responsive.
"""
from __future__ import annotations

import os
import shutil
from typing import Optional

from . import align, clips, db, media, qa
from .config import settings

ALIGN_SR = 8000


# --------------------------------------------------------------------------- #
# Watch sheet
# --------------------------------------------------------------------------- #
def build_sheet(clip_ids: list[str]) -> dict:
    s = settings()
    rows = [db.get("clips", cid) for cid in clip_ids]
    missing = [cid for cid, r in zip(clip_ids, rows) if not r]
    if missing:
        raise clips.TransitionError(f"Unknown clip(s): {', '.join(missing)}")
    wrong = [r["id"] for r in rows if r["status"] != "shortlisted"]
    if wrong:
        raise clips.TransitionError("Only shortlisted clips can go on a watch sheet.")
    sheet_id = db.new_id()
    out = s.path("sheets", f"{sheet_id}.mp4")
    entries = [{"clip_id": r["id"], "number": i + 1, "path": r["raw_path"]}
               for i, r in enumerate(rows)]
    manifest = media.build_watch_sheet(entries, out, s.tone_hz, s.tone_seconds,
                                       s.card_seconds, s.reaction_tail_seconds)
    db.insert("watch_sheets", {"id": sheet_id, "path": out, "manifest": manifest,
                               "status": "awaiting_recording", "created_at": db.iso()})
    for r in rows:
        clips.transition(r["id"], "awaiting_reaction")
    return db.get("watch_sheets", sheet_id)


def list_sheets() -> list[dict]:
    return db.query("SELECT * FROM watch_sheets ORDER BY created_at DESC")


# --------------------------------------------------------------------------- #
# Reaction session
# --------------------------------------------------------------------------- #
def ingest_reaction(sheet_id: str, uploaded_path: str) -> dict:
    """Store a recording for a sheet, align it, and cut one segment per clip."""
    s = settings()
    sheet = db.get("watch_sheets", sheet_id)
    if not sheet:
        raise clips.TransitionError("Watch sheet not found.")
    info = media.probe(uploaded_path)
    if not (info["has_video"] and info["has_audio"]):
        raise media.MediaError("The recording needs both video and audio.")
    session_id = db.new_id()
    ext = os.path.splitext(uploaded_path)[1].lower() or ".mp4"
    dest = s.path("reactions", f"{session_id}{ext}")
    shutil.move(uploaded_path, dest)
    db.insert("reaction_sessions", {"id": session_id, "sheet_id": sheet_id, "path": dest,
                                    "status": "aligning", "created_at": db.iso()})
    try:
        result = align_session(session_id)
    except Exception as e:  # noqa: BLE001 - recorded on the session for the UI
        db.update("reaction_sessions", session_id, {"status": "failed", "error": str(e)[:500]})
        raise
    db.update("watch_sheets", sheet_id, {"status": "recorded"})
    return result


def align_session(session_id: str) -> dict:
    s = settings()
    session = db.get("reaction_sessions", session_id)
    sheet = db.get("watch_sheets", session["sheet_id"])
    manifest = sheet["manifest"]
    audio = media.read_audio(session["path"], ALIGN_SR)
    detected = align.detect_tones(audio, ALIGN_SR, s.tone_hz, s.tone_seconds)
    expected = [m["tone_at_s"] for m in manifest]
    offset, matched = align.match(detected, expected)
    if offset is None:
        db.update("reaction_sessions", session_id, {
            "status": "failed", "detected_tones": detected,
            "error": "No sync tones found. Play the sheet through speakers the mic can hear."})
        raise media.MediaError("No sync tones were found in the recording.")
    db.execute("DELETE FROM reaction_segments WHERE session_id = ?", (session_id,))
    segments = []
    for m, hit in zip(manifest, matched):
        tone_at = hit if hit is not None else m["tone_at_s"] + offset
        clip_start = tone_at + s.tone_seconds + s.card_seconds
        seg = {
            "id": db.new_id(), "session_id": session_id, "clip_id": m["clip_id"],
            "clip_start_s": round(clip_start, 3),
            "clip_duration_s": m["clip_duration_s"], "tail_s": m["tail_s"],
            "manual_offset_ms": 0, "tone_detected": 1 if hit is not None else 0,
            "created_at": db.iso(),
        }
        seg.update(_tail_measure(audio, seg))
        db.insert("reaction_segments", seg)
        db.update("clips", m["clip_id"], {"reaction_segment_id": seg["id"], "updated_at": db.iso()})
        segments.append(seg)
    db.update("reaction_sessions", session_id, {
        "status": "aligned", "detected_tones": detected, "offset_s": round(offset, 3),
        "error": None})
    return {"session": db.get("reaction_sessions", session_id), "segments": segments}


def _tail_measure(audio, seg: dict) -> dict:
    start = seg["clip_start_s"] + seg["manual_offset_ms"] / 1000.0
    tail_start = start + seg["clip_duration_s"]
    prof = align.speech_profile(audio, ALIGN_SR, tail_start, tail_start + seg["tail_s"])
    return {"speech_seconds": prof["speech_seconds"]}


def adjust_segment(segment_id: str, manual_offset_ms: int) -> dict:
    seg = db.get("reaction_segments", segment_id)
    if not seg:
        raise clips.TransitionError("Segment not found.")
    if abs(manual_offset_ms) > 10_000:
        raise clips.TransitionError("Offsets are limited to ±10 s.")
    session = db.get("reaction_sessions", seg["session_id"])
    audio = media.read_audio(session["path"], ALIGN_SR)
    seg["manual_offset_ms"] = int(manual_offset_ms)
    db.update("reaction_segments", segment_id, {
        "manual_offset_ms": seg["manual_offset_ms"], **_tail_measure(audio, seg)})
    return db.get("reaction_segments", segment_id)


# --------------------------------------------------------------------------- #
# Compose + QA
# --------------------------------------------------------------------------- #
def trimmed_tail(audio, seg: dict, tail_s: float) -> float:
    """End the closing comment shortly after you stop talking (min 2 s)."""
    start = seg["clip_start_s"] + seg["manual_offset_ms"] / 1000.0 + seg["clip_duration_s"]
    prof = align.speech_profile(audio, ALIGN_SR, start, start + tail_s)
    if prof["last_speech_end_s"] is None:
        return min(tail_s, 2.0)
    return round(min(tail_s, max(2.0, prof["last_speech_end_s"] - start + 0.6)), 2)


def compose_clip(clip_id: str) -> dict:
    """Render clip + reaction, run QA, and move the clip to review or qa_failed."""
    s = settings()
    clip = db.get("clips", clip_id)
    if not clip or not clip.get("reaction_segment_id"):
        raise clips.TransitionError("This clip has no aligned reaction yet.")
    if clip["status"] in ("awaiting_reaction", "qa_failed", "pending_review"):
        clip = clips.transition(clip_id, "composing")
    elif clip["status"] != "composing":
        raise clips.TransitionError(f"A {clip['status']} clip cannot be composed.")
    seg = db.get("reaction_segments", clip["reaction_segment_id"])
    session = db.get("reaction_sessions", seg["session_id"])
    audio = media.read_audio(session["path"], ALIGN_SR)
    tail = trimmed_tail(audio, seg, seg["tail_s"])
    out = s.path("composed", f"{clip_id}.mp4")
    try:
        media.compose(
            clip["raw_path"], session["path"],
            seg["clip_start_s"] + seg["manual_offset_ms"] / 1000.0,
            seg["clip_duration_s"], tail, clip.get("layout") or "stacked", out,
            loudness_target=s.loudness_target,
            reaction_audio_during_clip=os.environ.get(
                "PIPELINE_REACTION_AUDIO_DURING_CLIP", "0").lower() in ("1", "true", "yes"))
    except media.MediaError as e:
        return clips.transition(clip_id, "qa_failed", qa_report={
            "passed": False, "checks": [{"check": "render", "passed": False,
                                         "value": None, "limit": None, "detail": str(e)}]})
    report = qa.check(out, seg.get("speech_seconds"))
    return clips.transition(
        clip_id, "pending_review" if report["passed"] else "qa_failed",
        composed_path=out, qa_report=report)


def compose_pending() -> int:
    """Compose every clip whose reaction is aligned but not rendered yet."""
    done = 0
    for c in db.query("SELECT id FROM clips WHERE status = 'awaiting_reaction' "
                      "AND reaction_segment_id IS NOT NULL"):
        try:
            compose_clip(c["id"])
            done += 1
        except Exception as e:  # noqa: BLE001 - one bad clip must not stop the batch
            print(f"⚠️ Pipeline compose failed for {c['id']}: {e}")
    return done


def segment_for(clip_id: str) -> Optional[dict]:
    clip = db.get("clips", clip_id)
    if not clip or not clip.get("reaction_segment_id"):
        return None
    return db.get("reaction_segments", clip["reaction_segment_id"])
