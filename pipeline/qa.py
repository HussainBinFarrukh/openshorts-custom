"""QA gates for a composed clip. A clip that fails any check cannot reach review."""
from __future__ import annotations

from typing import Optional

from . import media
from .config import settings


def check(path: str, commentary_speech_s: Optional[float]) -> dict:
    s = settings()
    checks = []

    def add(name: str, ok: bool, value, limit, detail: str = ""):
        checks.append({"check": name, "passed": bool(ok), "value": value,
                       "limit": limit, "detail": detail})

    info = media.probe(path)
    dur = round(info["duration"], 2)
    add("duration", 3.0 <= dur <= s.shorts_max_seconds, dur, f"3-{s.shorts_max_seconds} s",
        "YouTube treats vertical videos up to 3 minutes as Shorts.")
    add("vertical", bool(info["width"] and info["height"] and info["height"] > info["width"]),
        f"{info['width']}x{info['height']}", "height > width")

    lufs = media.measure_loudness(path) if info["has_audio"] else None
    add("loudness", lufs is not None and abs(lufs - s.loudness_target) <= s.loudness_tolerance,
        None if lufs is None else round(lufs, 1),
        f"{s.loudness_target} ± {s.loudness_tolerance} LUFS")

    blacks = media.detect_black(path, 2.0)
    add("black_frames", not blacks, [[round(a, 1), round(b, 1)] for a, b in blacks],
        "no black stretch over 2 s")

    silences = media.detect_silence(path, -50.0, 3.0) if info["has_audio"] else [(0.0, dur)]
    add("silence", not silences, [[round(a, 1), round(b, 1)] for a, b in silences],
        "no silence over 3 s")

    speech = float(commentary_speech_s or 0.0)
    add("commentary", speech >= s.min_commentary_seconds, round(speech, 2),
        f">= {s.min_commentary_seconds} s of your speech",
        "Measured in the closing comment after the clip, where only your voice is heard.")

    return {"passed": all(c["passed"] for c in checks), "checks": checks}
