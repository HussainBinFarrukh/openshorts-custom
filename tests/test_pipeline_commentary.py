"""End-to-end commentary flow with real ffmpeg: sheet -> recording -> align -> compose -> QA -> approve.

The "recording" is synthesised from the sheet itself: a lead-in before play,
the sheet's audio as a mic would hear it, and speech-like sound in each
closing-comment window. Skipped when ffmpeg is not installed.
"""
import os
import shutil
import subprocess
import wave

import numpy as np
import pytest

from pipeline import clips, commentary, db, media, scheduler

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

SR = 48000
LEAD_IN = 2.3


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_DATA_DIR", str(tmp_path / "pipe"))
    monkeypatch.setenv("PIPELINE_REACTION_TAIL_SECONDS", "6")
    monkeypatch.setenv("PIPELINE_MIN_COMMENTARY_SECONDS", "3")
    monkeypatch.setenv("PIPELINE_TIMEZONE", "America/New_York")
    db.init()
    return tmp_path


def _make_clip(path, seconds=4, hz=440):
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc2=s=1080x1920:r=30:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate=48000:duration={seconds},volume=0.4",
        "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(path)], check=True)


def _speechlike(seconds, seed):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    noise = np.convolve(rng.normal(0, 1, n), np.ones(6) / 6, mode="same")
    env = 0.5 * (1 + np.sin(2 * np.pi * 4 * np.arange(n) / SR))
    return 0.25 * noise * env


def _make_recording(sheet, out, speech_seconds=4.0):
    audio = media.read_audio(sheet["path"], SR) * 0.5          # heard through speakers
    audio = np.concatenate([np.zeros(int(LEAD_IN * SR), dtype=np.float32), audio,
                            np.zeros(int(1.0 * SR), dtype=np.float32)])
    audio += np.random.default_rng(3).normal(0, 0.002, audio.size).astype(np.float32)
    for i, m in enumerate(sheet["manifest"] if speech_seconds > 0 else []):
        start = LEAD_IN + m["clip_start_s"] + m["clip_duration_s"] + 0.4
        a = int(start * SR)
        seg = _speechlike(speech_seconds, i)
        audio[a:a + seg.size] += seg.astype(np.float32)
    wav = str(out) + ".wav"
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    dur = audio.size / SR
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=30:d={dur:.3f}", "-i", wav,
        "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(out)], check=True)
    os.unlink(wav)


def _draft(path):
    cid = db.new_id()
    db.insert("clips", {"id": cid, "openshorts_job_id": db.new_id(), "clip_index": 0,
                        "status": "draft", "title": "Pricing is a product decision",
                        "raw_path": str(path), "created_at": db.iso(), "updated_at": db.iso()})
    return cid


def test_full_commentary_flow(pipe):
    ids = []
    for i in range(2):
        p = pipe / f"clip{i}.mp4"
        _make_clip(p, hz=440 + 110 * i)
        cid = _draft(p)
        clips.transition(cid, "shortlisted")
        ids.append(cid)
    db.update("clips", ids[1], {"layout": "pip"})

    sheet = commentary.build_sheet(ids)
    assert os.path.isfile(sheet["path"])
    assert [m["number"] for m in sheet["manifest"]] == [1, 2]
    assert all(db.get("clips", c)["status"] == "awaiting_reaction" for c in ids)

    rec = pipe / "reaction.mp4"
    _make_recording(sheet, rec)
    result = commentary.ingest_reaction(sheet["id"], str(rec))
    segs = result["segments"]
    assert len(segs) == 2 and all(s["tone_detected"] for s in segs)
    for seg, m in zip(segs, sheet["manifest"]):
        assert abs(seg["clip_start_s"] - (m["clip_start_s"] + LEAD_IN)) < 0.05
        assert seg["speech_seconds"] >= 3.0
    assert abs(result["session"]["offset_s"] - LEAD_IN) < 0.05

    assert commentary.compose_pending() == 2
    for cid in ids:
        clip = db.get("clips", cid)
        assert clip["status"] == "pending_review", clip["qa_report"]
        info = media.probe(clip["composed_path"])
        assert (info["width"], info["height"]) == (1080, 1920)
        # clip (4 s) + closing comment trimmed to ~0.6 s after speech ends
        assert 7.0 <= info["duration"] <= 10.5
        checks = {c["check"]: c for c in clip["qa_report"]["checks"]}
        assert checks["loudness"]["passed"] and checks["commentary"]["passed"]

    row = scheduler.approve(ids[0], "HBF")
    assert row["status"] == "scheduled"


def test_recording_without_tones_fails_cleanly(pipe):
    p = pipe / "clip.mp4"
    _make_clip(p)
    cid = _draft(p)
    clips.transition(cid, "shortlisted")
    sheet = commentary.build_sheet([cid])
    rec = pipe / "silent_reaction.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error",
                    "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=12",
                    "-f", "lavfi", "-i", "anoisesrc=d=12:a=0.01",
                    "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(rec)], check=True)
    with pytest.raises(media.MediaError):
        commentary.ingest_reaction(sheet["id"], str(rec))
    assert db.get("clips", cid)["status"] == "awaiting_reaction"
    session = db.query("SELECT * FROM reaction_sessions")[0]
    assert session["status"] == "failed" and "tones" in session["error"]


def test_qa_rejects_a_reaction_with_no_closing_comment(pipe):
    p = pipe / "clip.mp4"
    _make_clip(p)
    cid = _draft(p)
    clips.transition(cid, "shortlisted")
    sheet = commentary.build_sheet([cid])
    rec = pipe / "quiet.mp4"
    _make_recording(sheet, rec, speech_seconds=0.0)
    commentary.ingest_reaction(sheet["id"], str(rec))
    commentary.compose_pending()
    clip = db.get("clips", cid)
    assert clip["status"] == "qa_failed"
    failed = [c["check"] for c in clip["qa_report"]["checks"] if not c["passed"]]
    assert "commentary" in failed
    with pytest.raises(clips.TransitionError):
        scheduler.approve(cid, "HBF")
