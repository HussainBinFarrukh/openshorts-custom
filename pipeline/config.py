"""Pipeline settings, read from the environment each time ``settings()`` is called.

Reading lazily (instead of freezing at import) lets tests and a running server
pick up a changed ``.env`` without re-importing the package.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def parse_window(raw: str) -> tuple[time, time]:
    """``"09:00-21:00"`` -> (09:00, 21:00). Falls back to 09-21 on bad input."""
    try:
        start_s, end_s = raw.split("-", 1)
        sh, sm = (int(x) for x in start_s.strip().split(":"))
        eh, em = (int(x) for x in end_s.strip().split(":"))
        start, end = time(sh, sm), time(eh, em)
        if start >= end:
            raise ValueError("window must not wrap midnight")
        return start, end
    except (ValueError, AttributeError):
        return time(9, 0), time(21, 0)


@dataclass(frozen=True)
class Settings:
    enabled: bool
    data_dir: str
    timezone: str
    admin_token: str

    intake_every_minutes: int
    intake_daily_limit: int
    max_video_age_days: int
    max_source_minutes: int
    shorts_max_seconds: int

    publish_max_per_day: int
    publish_min_gap_minutes: int
    publish_window: tuple[time, time]

    yt_client_id: str
    yt_client_secret: str
    yt_api_key: str
    yt_redirect_uri: str
    yt_daily_quota: int
    yt_upload_cost: int
    yt_app_verified: bool
    default_privacy: str
    yt_category_id: str

    min_commentary_seconds: float
    reaction_tail_seconds: float
    tone_hz: float
    tone_seconds: float
    card_seconds: float
    loudness_target: float
    loudness_tolerance: float

    @property
    def privacy(self) -> str:
        """YouTube locks unverified-app uploads to private, so ask for that."""
        if not self.yt_app_verified:
            return "private"
        return self.default_privacy if self.default_privacy in (
            "public", "unlisted", "private") else "private"

    def path(self, *parts: str) -> str:
        full = os.path.join(self.data_dir, *parts)
        os.makedirs(os.path.dirname(full) if os.path.splitext(full)[1] else full,
                    exist_ok=True)
        return full


def settings() -> Settings:
    return Settings(
        enabled=_flag("PIPELINE_ENABLED", True),
        data_dir=os.environ.get("PIPELINE_DATA_DIR", "pipeline_data"),
        timezone=os.environ.get("PIPELINE_TIMEZONE", "America/New_York"),
        admin_token=os.environ.get("PIPELINE_ADMIN_TOKEN", ""),
        intake_every_minutes=max(5, _int("PIPELINE_INTAKE_EVERY_MINUTES", 60)),
        intake_daily_limit=max(0, _int("PIPELINE_INTAKE_DAILY_LIMIT", 2)),
        max_video_age_days=max(1, _int("PIPELINE_MAX_VIDEO_AGE_DAYS", 3)),
        max_source_minutes=max(5, _int("PIPELINE_MAX_SOURCE_MINUTES", 45)),
        shorts_max_seconds=_int("PIPELINE_SHORTS_MAX_SECONDS", 180),
        publish_max_per_day=max(0, _int("PIPELINE_PUBLISH_MAX_PER_DAY", 3)),
        publish_min_gap_minutes=max(0, _int("PIPELINE_PUBLISH_MIN_GAP_MINUTES", 180)),
        publish_window=parse_window(os.environ.get("PIPELINE_PUBLISH_WINDOW", "09:00-21:00")),
        yt_client_id=os.environ.get("PIPELINE_YT_CLIENT_ID", ""),
        yt_client_secret=os.environ.get("PIPELINE_YT_CLIENT_SECRET", ""),
        yt_api_key=os.environ.get("PIPELINE_YT_API_KEY", ""),
        yt_redirect_uri=os.environ.get(
            "PIPELINE_YT_REDIRECT_URI", "http://localhost:8000/api/pipeline/youtube/callback"),
        yt_daily_quota=_int("PIPELINE_YT_DAILY_QUOTA", 10000),
        yt_upload_cost=_int("PIPELINE_YT_UPLOAD_COST", 1600),
        yt_app_verified=_flag("PIPELINE_YT_APP_VERIFIED", False),
        default_privacy=os.environ.get("PIPELINE_DEFAULT_PRIVACY", "public"),
        yt_category_id=os.environ.get("PIPELINE_YT_CATEGORY_ID", "22"),
        min_commentary_seconds=_float("PIPELINE_MIN_COMMENTARY_SECONDS", 5.0),
        reaction_tail_seconds=_float("PIPELINE_REACTION_TAIL_SECONDS", 12.0),
        tone_hz=_float("PIPELINE_TONE_HZ", 1000.0),
        tone_seconds=_float("PIPELINE_TONE_SECONDS", 0.6),
        card_seconds=_float("PIPELINE_CARD_SECONDS", 1.5),
        loudness_target=_float("PIPELINE_LOUDNESS_TARGET", -14.0),
        loudness_tolerance=_float("PIPELINE_LOUDNESS_TOLERANCE", 2.0),
    )
