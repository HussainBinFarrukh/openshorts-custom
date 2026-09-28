"""FFmpeg helpers for the commentary and QA stages.

Everything here shells out to ffmpeg/ffprobe (already in the OpenShorts image)
and uses numpy only for audio analysis, so none of it needs the ML stack.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional

import numpy as np

W, H, FPS, SR = 1080, 1920, 30, 48000
FONT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "fonts", "Montserrat-ExtraBold.ttf")
ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
          "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2",
          "-movflags", "+faststart"]


class MediaError(RuntimeError):
    pass


def run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise MediaError(f"{os.path.basename(cmd[0])} failed: {tail}")
    return proc


def probe(path: str) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", path]).stdout
    data = json.loads(out or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    return {
        "duration": float(data.get("format", {}).get("duration") or 0.0),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "has_video": video is not None,
        "width": int(video["width"]) if video else None,
        "height": int(video["height"]) if video else None,
    }


def _escape_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019")


# --------------------------------------------------------------------------- #
# Watch sheet
# --------------------------------------------------------------------------- #
def build_watch_sheet(entries: list[dict], out_path: str, tone_hz: float, tone_s: float,
                      card_s: float, tail_s: float) -> list[dict]:
    """Concatenate [tone | ID card | clip | black tail] per entry into one MP4.

    ``entries``: [{"clip_id", "number", "path"}]. Returns the manifest with each
    entry's exact times on the sheet, computed from the segments we render.
    """
    if not entries:
        raise MediaError("No clips to put on a watch sheet.")
    tmp = tempfile.mkdtemp(prefix="sheet_")
    try:
        parts, manifest, cursor = [], [], 0.0
        for e in entries:
            info = probe(e["path"])
            dur = info["duration"]
            seg = os.path.join(tmp, f"seg_{e['number']:03d}.mp4")
            label = _escape_text(f"CLIP {e['number']}")
            card = (f"drawtext=fontfile='{FONT}':text='{label}':fontcolor=white:fontsize=140:"
                    f"x=(w-text_w)/2:y=(h-text_h)/2" if os.path.isfile(FONT) else "null")
            clip_audio = (f"[3:a]aresample={SR},aformat=channel_layouts=stereo[ca]"
                          if info["has_audio"] else
                          f"anullsrc=r={SR}:cl=stereo,atrim=0:{dur:.3f}[ca]")
            fc = ";".join([
                f"color=c=black:s={W}x{H}:r={FPS}:d={tone_s:.3f}[tv]",
                f"color=c=0x1d1d1d:s={W}x{H}:r={FPS}:d={card_s:.3f},{card}[cv]",
                f"[3:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={FPS}[clv]",
                f"color=c=black:s={W}x{H}:r={FPS}:d={tail_s:.3f}[bv]",
                f"[0:a]aformat=channel_layouts=stereo[ta]",
                f"[1:a]aformat=channel_layouts=stereo[sa]",
                clip_audio,
                f"[2:a]aformat=channel_layouts=stereo[ba]",
                "[tv][ta][cv][sa][clv][ca][bv][ba]concat=n=4:v=1:a=1[v][a]",
            ])
            run(["ffmpeg", "-y", "-v", "error",
                 "-f", "lavfi", "-t", f"{tone_s:.3f}",
                 "-i", f"sine=frequency={tone_hz}:sample_rate={SR}:duration={tone_s:.3f},volume=0.7",
                 "-f", "lavfi", "-t", f"{card_s:.3f}", "-i", f"anullsrc=r={SR}:cl=stereo",
                 "-f", "lavfi", "-t", f"{tail_s:.3f}", "-i", f"anullsrc=r={SR}:cl=stereo",
                 "-i", e["path"],
                 "-filter_complex", fc, "-map", "[v]", "-map", "[a]", *ENCODE, seg])
            seg_dur = probe(seg)["duration"]
            manifest.append({
                "clip_id": e["clip_id"],
                "number": e["number"],
                "tone_at_s": round(cursor, 3),
                "clip_start_s": round(cursor + tone_s + card_s, 3),
                "clip_duration_s": round(dur, 3),
                "tail_s": tail_s,
            })
            cursor += seg_dur
            parts.append(seg)
        listing = os.path.join(tmp, "list.txt")
        with open(listing, "w") as fh:
            fh.writelines(f"file '{p}'\n" for p in parts)
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listing,
             "-c", "copy", "-movflags", "+faststart", out_path])
        return calibrate_manifest(out_path, manifest, tone_hz, tone_s, card_s)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def calibrate_manifest(sheet_path: str, manifest: list[dict], tone_hz: float,
                       tone_s: float, card_s: float) -> list[dict]:
    """Replace planned tone times with the ones measured in the finished sheet.

    Container durations include encoder padding (AAC priming, a trailing video
    frame), so summing segment durations drifts tens of milliseconds per clip.
    The tones in the sheet's own audio are the ground truth the recording will
    be matched against.
    """
    from . import align  # local import: align is pure numpy, media is ffmpeg glue

    audio = read_audio(sheet_path, 8000)
    found = align.detect_tones(audio, 8000, tone_hz, tone_s)
    if len(found) != len(manifest):
        return manifest
    for m, t in zip(manifest, found):
        m["tone_at_s"] = round(t, 3)
        m["clip_start_s"] = round(t + tone_s + card_s, 3)
    return manifest


# --------------------------------------------------------------------------- #
# Audio analysis
# --------------------------------------------------------------------------- #
def read_audio(path: str, sr: int = 16000) -> np.ndarray:
    """Decode the first audio track to mono float32 in [-1, 1]."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr),
         "-f", "s16le", "-"], capture_output=True, timeout=1800)
    if proc.returncode != 0:
        raise MediaError(f"ffmpeg could not decode audio: {proc.stderr.decode()[-400:]}")
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def measure_loudness(path: str) -> Optional[float]:
    """Integrated loudness (LUFS) via the ebur128 filter; None if no audio."""
    proc = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", path,
                           "-filter_complex", "ebur128=framelog=quiet", "-f", "null", "-"],
                          capture_output=True, text=True, timeout=1800)
    matches = re.findall(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", proc.stderr)
    if not matches or matches[-1] == "-inf":
        return None
    return float(matches[-1])


def detect_black(path: str, min_duration: float = 2.0) -> list[tuple[float, float]]:
    proc = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", path, "-vf",
                           f"blackdetect=d={min_duration}:pix_th=0.10", "-an", "-f", "null", "-"],
                          capture_output=True, text=True, timeout=1800)
    return [(float(a), float(b)) for a, b in
            re.findall(r"black_start:([\d.]+)\s+black_end:([\d.]+)", proc.stderr)]


def detect_silence(path: str, noise_db: float = -50.0,
                   min_duration: float = 3.0) -> list[tuple[float, float]]:
    proc = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", path, "-af",
                           f"silencedetect=n={noise_db}dB:d={min_duration}", "-vn", "-f", "null", "-"],
                          capture_output=True, text=True, timeout=1800)
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", proc.stderr)]
    total = probe(path)["duration"]
    out = []
    for i, s in enumerate(starts):
        out.append((max(0.0, s), ends[i] if i < len(ends) else total))
    return out


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #
def compose(clip_path: str, reaction_path: str, reaction_clip_start_s: float,
            clip_duration_s: float, tail_s: float, layout: str, out_path: str,
            loudness_target: float = -14.0, reaction_audio_during_clip: bool = False) -> None:
    """Render the final vertical video.

    Part 1 (clip duration): the clip with the reaction video (stacked on top at
    40% of the height, or picture-in-picture), clip audio. If the reaction was
    recorded on headphones (``reaction_audio_during_clip``) your voice is mixed
    in and the clip audio is ducked under it; with speakers the mic also hears
    the clip, so the reaction audio stays out of this part to avoid an echo.
    Part 2 (tail): your reaction full-frame with your audio, the closing comment.
    """
    rinfo = probe(reaction_path)
    if not rinfo["has_video"]:
        raise MediaError("The reaction recording has no video track.")
    if not rinfo["has_audio"]:
        raise MediaError("The reaction recording has no audio track.")
    cinfo = probe(clip_path)
    d, t = clip_duration_s, max(0.0, tail_s)
    top_h = int(H * 0.4)
    bot_h = H - top_h

    if layout == "pip":
        pw, ph = 420, 560
        part1_video = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={FPS}[base];"
            f"[r1]scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},"
            f"setsar=1[pip];"
            f"[base][pip]overlay=x=W-w-40:y=140[p1v]")
    else:
        part1_video = (
            f"[r1]scale={W}:{top_h}:force_original_aspect_ratio=increase,"
            f"crop={W}:{top_h},setsar=1[top];"
            f"[0:v]split[c1][c2];"
            f"[c1]scale={W}:{bot_h}:force_original_aspect_ratio=increase,crop={W}:{bot_h},"
            f"boxblur=24:2,setsar=1[bg];"
            f"[c2]scale={W}:{bot_h}:force_original_aspect_ratio=decrease,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS}[bottom];"
            f"[top][bottom]vstack=inputs=2[p1v]")

    clip_audio = (f"[0:a]atrim=duration={d:.3f},asetpts=PTS-STARTPTS,aresample={SR},"
                  f"aformat=channel_layouts=stereo[ca]" if cinfo["has_audio"]
                  else f"anullsrc=r={SR}:cl=stereo,atrim=0:{d:.3f}[ca]")
    if reaction_audio_during_clip:
        part1_audio = (
            f"{clip_audio};[ra1]aformat=channel_layouts=stereo,asplit[rv][rk];"
            f"[ca][rk]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
            f"[duck][rv]amix=inputs=2:normalize=0[p1a]")
    else:
        part1_audio = f"{clip_audio};[ra1]anullsink;[ca]anull[p1a]"

    parts = [
        # The clip, trimmed to the length the manifest says it has.
        f"[0:v]trim=duration={d:.3f},setpts=PTS-STARTPTS[cv0]",
        # The reaction window: clip-length part for part 1, the rest is the tail.
        f"[1:v]trim=start={reaction_clip_start_s:.3f}:duration={d + t:.3f},"
        f"setpts=PTS-STARTPTS,fps={FPS},split[rva][rvb]",
        f"[rva]trim=duration={d:.3f},setpts=PTS-STARTPTS[r1]",
        f"[rvb]trim=start={d:.3f},setpts=PTS-STARTPTS,"
        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[p2v]",
        f"[1:a]atrim=start={reaction_clip_start_s:.3f}:duration={d + t:.3f},"
        f"asetpts=PTS-STARTPTS,aresample={SR},asplit[raa][rab]",
        f"[raa]atrim=duration={d:.3f},asetpts=PTS-STARTPTS[ra1]",
        f"[rab]atrim=start={d:.3f},asetpts=PTS-STARTPTS,aformat=channel_layouts=stereo[p2a]",
        part1_video.replace("[0:v]", "[cv0]"),
        part1_audio,
    ]
    norm = f"loudnorm=I={loudness_target}:TP=-1.5:LRA=11,aresample={SR}"
    if t > 0.05:
        parts.append(f"[p1v][p1a][p2v][p2a]concat=n=2:v=1:a=1[vv][aa]")
        parts.append(f"[aa]{norm}[ao]")
        vmap = "[vv]"
    else:
        parts += ["[p2v]nullsink", "[p2a]anullsink", f"[p1a]{norm}[ao]"]
        vmap = "[p1v]"
    fc = ";".join(parts)
    run(["ffmpeg", "-y", "-v", "error", "-i", clip_path, "-i", reaction_path,
         "-filter_complex", fc, "-map", vmap, "-map", "[ao]", *ENCODE, out_path],
        timeout=3600)
