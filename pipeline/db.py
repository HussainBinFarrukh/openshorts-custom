"""SQLite store for the pipeline.

The self-hosted app has no database of its own (jobs live in memory and on
disk), and the pipeline's state is small and single-writer, so stdlib sqlite3
is enough and adds no dependency. Every public function opens its own
connection: the pipeline runs in asyncio tasks and executor threads, and a
per-call connection is the simplest way to stay thread-safe.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .config import settings

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS watchlist (
    id TEXT PRIMARY KEY,
    channel_input TEXT NOT NULL,
    channel_id TEXT,
    uploads_playlist_id TEXT,
    title TEXT,
    permission_note TEXT NOT NULL,
    permission_granted_at TEXT,
    added_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    last_checked_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS source_videos (
    id TEXT PRIMARY KEY,
    watch_id TEXT,
    youtube_video_id TEXT UNIQUE,
    url TEXT NOT NULL,
    title TEXT,
    published_at TEXT,
    duration_s REAL,
    status TEXT NOT NULL,
    skip_reason TEXT,
    openshorts_job_id TEXT UNIQUE,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    source_video_id TEXT,
    openshorts_job_id TEXT NOT NULL,
    clip_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    title TEXT,
    description TEXT,
    tags TEXT,
    hook_text TEXT,
    start_s REAL,
    end_s REAL,
    duration_s REAL,
    raw_path TEXT NOT NULL,
    layout TEXT NOT NULL DEFAULT 'stacked',
    reaction_segment_id TEXT,
    composed_path TEXT,
    qa_report TEXT,
    approved_by TEXT,
    approved_at TEXT,
    review_note TEXT,
    scheduled_for TEXT,
    youtube_video_id TEXT,
    published_at TEXT,
    publish_error TEXT,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (openshorts_job_id, clip_index)
);

CREATE TABLE IF NOT EXISTS watch_sheets (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    manifest TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reaction_sessions (
    id TEXT PRIMARY KEY,
    sheet_id TEXT NOT NULL,
    path TEXT NOT NULL,
    status TEXT NOT NULL,
    detected_tones TEXT,
    offset_s REAL,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reaction_segments (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    clip_id TEXT NOT NULL,
    clip_start_s REAL NOT NULL,
    clip_duration_s REAL NOT NULL,
    tail_s REAL NOT NULL,
    manual_offset_ms INTEGER NOT NULL DEFAULT 0,
    tone_detected INTEGER NOT NULL DEFAULT 1,
    speech_seconds REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quota_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    units INTEGER NOT NULL,
    op TEXT NOT NULL,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT PRIMARY KEY,
    access_token TEXT,
    refresh_token TEXT,
    expires_at TEXT,
    scope TEXT,
    channel_id TEXT,
    channel_title TEXT,
    state TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL,
    checkpoint TEXT NOT NULL,
    pulled_at TEXT NOT NULL,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    avg_view_duration_s REAL,
    avg_view_pct REAL,
    subscribers_gained INTEGER,
    raw TEXT,
    UNIQUE (clip_id, checkpoint)
);

CREATE INDEX IF NOT EXISTS ix_clips_status ON clips (status);
CREATE INDEX IF NOT EXISTS ix_sources_status ON source_videos (status);
CREATE INDEX IF NOT EXISTS ix_quota_day ON quota_ledger (day);
"""

JSON_COLUMNS = {"tags", "qa_report", "meta_json", "manifest", "detected_tones", "raw"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime] = None) -> str:
    return (dt or utcnow()).astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


def db_path() -> str:
    s = settings()
    os.makedirs(s.data_dir, exist_ok=True)
    return os.path.join(s.data_dir, "pipeline.db")


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),))


def _encode(key: str, value: Any) -> Any:
    if key in JSON_COLUMNS and value is not None and not isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    out = dict(row)
    for key in JSON_COLUMNS & out.keys():
        if isinstance(out[key], str):
            try:
                out[key] = json.loads(out[key])
            except ValueError:
                pass
    return out


def insert(table: str, values: dict) -> dict:
    cols = list(values)
    with connect() as conn:
        conn.execute(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [_encode(c, values[c]) for c in cols])
    return values


def update(table: str, row_id: Any, values: dict, key: str = "id") -> None:
    if not values:
        return
    sets = ", ".join(f"{c} = ?" for c in values)
    with connect() as conn:
        conn.execute(f"UPDATE {table} SET {sets} WHERE {key} = ?",
                     [_encode(c, v) for c, v in values.items()] + [row_id])


def get(table: str, row_id: Any, key: str = "id") -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE {key} = ?", (row_id,)).fetchone()
    return row_to_dict(row)


def query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [row_to_dict(r) for r in rows]


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.rowcount
