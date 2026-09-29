"""Reaction alignment: find the sync tones in a recording and map them to clips.

Tone detection uses complex demodulation at the tone frequency: the fraction of
a short window's power that sits in a narrow band around ``hz``. A pure tone
scores ~1; speech, music and room noise spread their power and score far
lower, so the tones stand out without a trained model.

Matching uses the sheet's own timeline: every tone is expected at
``tone_at_s + offset`` where ``offset`` is when you pressed play relative to
the start of the recording. The offset that lines up the most detections wins,
so a missed or spurious tone does not shift every clip after it.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

HOP_S = 0.01


def band_ratio(audio: np.ndarray, sr: int, hz: float, window_s: float = 0.05) -> np.ndarray:
    """Per-hop share of power inside a narrow band at ``hz`` (0..~1)."""
    hop = max(1, int(HOP_S * sr))
    n_hops = audio.size // hop
    if n_hops == 0:
        return np.zeros(0, dtype=np.float32)
    # Per-hop sums, computed in chunks so an hour of audio stays small in memory.
    demod_sum = np.empty(n_hops, dtype=np.complex128)
    power_sum = np.empty(n_hops, dtype=np.float64)
    chunk_hops = 50_000
    for c0 in range(0, n_hops, chunk_hops):
        c1 = min(n_hops, c0 + chunk_hops)
        seg = audio[c0 * hop:c1 * hop].astype(np.float64)
        t = (np.arange(seg.size) + c0 * hop) / sr
        demod = (seg * np.exp(-2j * np.pi * hz * t)).reshape(-1, hop)
        demod_sum[c0:c1] = demod.sum(axis=1)
        power_sum[c0:c1] = (seg.reshape(-1, hop) ** 2).sum(axis=1)
    k = max(1, int(round(window_s / HOP_S)))
    kernel = np.ones(k)
    samples = k * hop
    band = np.abs(np.convolve(demod_sum, kernel, mode="same") / samples) ** 2 * 2.0
    power = np.convolve(power_sum, kernel, mode="same") / samples
    ratio = np.where(power > 1e-7, band / np.maximum(power, 1e-12), 0.0)
    return ratio.astype(np.float32)


def detect_tones(audio: np.ndarray, sr: int, hz: float, tone_s: float,
                 threshold: float = 0.6, min_fraction: float = 0.6) -> list[float]:
    """Onset times (s) of stretches that look like the sync tone."""
    ratio = band_ratio(audio, sr, hz)
    on = ratio > threshold
    min_hops = int(tone_s * min_fraction / HOP_S)
    onsets, i = [], 0
    while i < on.size:
        if on[i]:
            j = i
            while j < on.size and on[j]:
                j += 1
            if j - i >= min_hops:
                onsets.append(round(i * HOP_S, 3))
            i = j
        else:
            i += 1
    return onsets


def match(detected: list[float], expected: list[float],
          tolerance: float = 0.3) -> tuple[Optional[float], list[Optional[float]]]:
    """Best recording offset and, per expected tone, the matched detection (or None)."""
    if not detected or not expected:
        return None, [None] * len(expected)
    best = (0, float("inf"), 0.0)          # (matches, residual, offset)
    for d in detected:
        for e in expected:
            off = d - e
            hits, resid = 0, 0.0
            for x in expected:
                gap = min(abs(y - (x + off)) for y in detected)
                if gap <= tolerance:
                    hits += 1
                    resid += gap
            if hits > best[0] or (hits == best[0] and resid < best[1]):
                best = (hits, resid, off)
    if best[0] == 0:
        return None, [None] * len(expected)
    off = best[2]
    matched, used = [], set()
    for x in expected:
        cands = [(abs(y - (x + off)), y) for y in detected if y not in used]
        gap, y = min(cands) if cands else (float("inf"), None)
        if y is not None and gap <= tolerance:
            matched.append(y)
            used.add(y)
        else:
            matched.append(None)
    diffs = [m - x for m, x in zip(matched, expected) if m is not None]
    return float(np.median(diffs)), matched


def speech_profile(audio: np.ndarray, sr: int, start_s: float, end_s: float,
                   frame_s: float = 0.03, margin_db: float = 12.0,
                   floor_db: float = -50.0) -> dict:
    """Energy VAD over [start, end): seconds of speech and when the last speech ends.

    The noise floor is the 10th percentile of frame levels across the whole
    recording, so a quiet room and a noisy one both get a sensible threshold.
    """
    frame = max(1, int(frame_s * sr))
    usable = audio[: (audio.size // frame) * frame]
    if usable.size == 0:
        return {"speech_seconds": 0.0, "last_speech_end_s": None}
    levels = 10 * np.log10(np.mean(usable.reshape(-1, frame) ** 2, axis=1) + 1e-12)
    threshold = max(float(np.percentile(levels, 10)) + margin_db, floor_db)
    a, b = int(start_s / frame_s), int(end_s / frame_s)
    window = levels[max(0, a):max(0, min(b, levels.size))]
    voiced = window > threshold
    if not voiced.any():
        return {"speech_seconds": 0.0, "last_speech_end_s": None}
    last = int(np.nonzero(voiced)[0][-1])
    return {"speech_seconds": round(float(voiced.sum()) * frame_s, 2),
            "last_speech_end_s": round((max(0, a) + last + 1) * frame_s, 2)}
