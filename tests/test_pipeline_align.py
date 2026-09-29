"""Tone detection, offset matching and the speech measure used for commentary QA."""
import numpy as np

from pipeline import align

SR = 8000


def _tone(seconds, hz=1000.0, amp=0.5):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def _speechlike(seconds, seed=0, amp=0.3):
    """Band-limited noise with a 4 Hz syllable envelope: broadband, like speech."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    noise = rng.normal(0, 1, n)
    noise = np.convolve(noise, np.ones(4) / 4, mode="same")
    env = 0.5 * (1 + np.sin(2 * np.pi * 4 * np.arange(n) / SR))
    return (amp * noise * env).astype(np.float32)


def _recording(tone_times, total, speech=()):
    rng = np.random.default_rng(1)
    audio = rng.normal(0, 0.003, int(total * SR)).astype(np.float32)   # room noise
    for start, dur in speech:
        a = int(start * SR)
        seg = _speechlike(dur, seed=int(start))
        audio[a:a + seg.size] += seg
    for t in tone_times:
        a = int(t * SR)
        tone = _tone(0.6)
        audio[a:a + tone.size] += tone
    return audio


def test_detects_tones_within_20ms_even_under_speech():
    truth = [2.37, 14.02, 29.55]
    audio = _recording(truth, 40, speech=[(0, 40)])
    found = align.detect_tones(audio, SR, 1000.0, 0.6)
    assert len(found) == 3
    for f, t in zip(found, truth):
        assert abs(f - t) < 0.02


def test_speech_alone_is_not_a_tone():
    audio = _recording([], 20, speech=[(0, 20)])
    assert align.detect_tones(audio, SR, 1000.0, 0.6) == []


def test_match_recovers_offset_and_flags_a_missed_tone():
    expected = [0.0, 11.4, 25.1, 37.9]
    offset = 4.25
    detected = [e + offset + 0.01 for i, e in enumerate(expected) if i != 2]   # tone 3 missed
    detected.append(19.0)                                                        # a spurious beep
    off, matched = align.match(sorted(detected), expected)
    assert abs(off - 4.26) < 0.02
    assert matched[2] is None
    assert all(m is not None for i, m in enumerate(matched) if i != 2)


def test_match_with_nothing_detected():
    off, matched = align.match([], [0.0, 5.0])
    assert off is None and matched == [None, None]


def test_speech_profile_measures_the_window_only():
    audio = _recording([], 30, speech=[(5, 4), (20, 6)])
    prof = align.speech_profile(audio, SR, 18, 30)
    assert 4.5 <= prof["speech_seconds"] <= 6.5
    assert 25.0 <= prof["last_speech_end_s"] <= 26.5
    quiet = align.speech_profile(audio, SR, 11, 19)
    assert quiet["speech_seconds"] < 0.5
