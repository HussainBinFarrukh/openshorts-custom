"""YouTube Data API v3 + Analytics API client: channel listing, OAuth, upload, stats.

Plain httpx, no Google SDK: the calls are few and the SDK would pull in a large
dependency tree for a self-hosted box. The client takes an optional
``httpx.AsyncClient`` so tests can inject ``httpx.MockTransport``.

Listing uses an API key (cheap, 1 unit per call, no user consent needed).
Uploading and analytics use the connected channel's OAuth token.
"""
from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx

from . import db, quota
from .config import settings

DATA_API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/videos"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)
CHUNK = 8 * 1024 * 1024
PROVIDER = "youtube"


class YouTubeError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, reauth: bool = False):
        super().__init__(message)
        self.status = status
        self.reauth = reauth


# --------------------------------------------------------------------------- #
# Parsing helpers (pure)
# --------------------------------------------------------------------------- #
_HANDLE = re.compile(r"(?:youtube\.com/)?(@[\w.\-]+)", re.I)
_CHANNEL_ID = re.compile(r"(UC[\w\-]{22})")
_DURATION = re.compile(
    r"P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+(?:\.\d+)?)S)?)?$")


def parse_channel_input(raw: str) -> dict:
    """Accept a channel URL, an @handle or a UC... id."""
    raw = (raw or "").strip()
    m = _CHANNEL_ID.search(raw)
    if m:
        return {"id": m.group(1)}
    m = _HANDLE.search(raw)
    if m:
        return {"forHandle": m.group(1)}
    raise ValueError("Use a channel URL, an @handle or a channel id (UC...).")


def parse_duration(value: Optional[str]) -> Optional[float]:
    """ISO-8601 video duration (``PT1H2M3S``) -> seconds."""
    if not value:
        return None
    m = _DURATION.match(value)
    if not m:
        return None
    parts = {k: float(v) if v else 0.0 for k, v in m.groupdict().items()}
    return parts["d"] * 86400 + parts["h"] * 3600 + parts["m"] * 60 + parts["s"]


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class YouTubeClient:
    def __init__(self, http: Optional[httpx.AsyncClient] = None):
        self._http = http
        self._owns = http is None

    async def __aenter__(self):
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=300.0))
        return self

    async def __aexit__(self, *exc):
        if self._owns and self._http is not None:
            await self._http.aclose()

    # ---- listing (API key) ------------------------------------------------ #
    async def _get_keyed(self, path: str, params: dict) -> dict:
        s = settings()
        if not s.yt_api_key:
            raise YouTubeError("PIPELINE_YT_API_KEY is not set.")
        resp = await self._http.get(f"{DATA_API}/{path}", params={**params, "key": s.yt_api_key})
        quota.record(quota.LIST_COST, f"{path}.list")
        if resp.status_code != 200:
            raise YouTubeError(_error_text(resp), resp.status_code)
        return resp.json()

    async def resolve_channel(self, channel_input: str) -> dict:
        lookup = parse_channel_input(channel_input)
        data = await self._get_keyed("channels", {"part": "snippet,contentDetails", **lookup})
        items = data.get("items") or []
        if not items:
            raise YouTubeError("Channel not found.")
        ch = items[0]
        return {
            "channel_id": ch["id"],
            "title": ch.get("snippet", {}).get("title"),
            "uploads_playlist_id": ch["contentDetails"]["relatedPlaylists"]["uploads"],
        }

    async def latest_uploads(self, playlist_id: str, limit: int = 10) -> list[dict]:
        data = await self._get_keyed("playlistItems", {
            "part": "snippet,contentDetails", "playlistId": playlist_id,
            "maxResults": min(max(limit, 1), 50)})
        ids = [it["contentDetails"]["videoId"] for it in data.get("items", [])]
        if not ids:
            return []
        details = await self._get_keyed("videos", {
            "part": "snippet,contentDetails,status", "id": ",".join(ids)})
        by_id = {v["id"]: v for v in details.get("items", [])}
        out = []
        for vid in ids:
            v = by_id.get(vid)
            if not v:
                continue
            snip = v.get("snippet", {})
            out.append({
                "video_id": vid,
                "title": snip.get("title"),
                "published_at": snip.get("publishedAt"),
                "duration_s": parse_duration(v.get("contentDetails", {}).get("duration")),
                "privacy": v.get("status", {}).get("privacyStatus"),
                "live": snip.get("liveBroadcastContent", "none"),
                "url": f"https://www.youtube.com/watch?v={vid}",
            })
        return out

    # ---- OAuth ------------------------------------------------------------ #
    @staticmethod
    def auth_url() -> str:
        s = settings()
        if not (s.yt_client_id and s.yt_client_secret):
            raise YouTubeError("PIPELINE_YT_CLIENT_ID / PIPELINE_YT_CLIENT_SECRET are not set.")
        state = secrets.token_urlsafe(24)
        _save_token({"state": state})
        return AUTH_URL + "?" + urlencode({
            "client_id": s.yt_client_id,
            "redirect_uri": s.yt_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        })

    async def exchange_code(self, code: str, state: str) -> dict:
        stored = db.get("oauth_tokens", PROVIDER, key="provider") or {}
        if not stored.get("state") or not secrets.compare_digest(stored["state"], state or ""):
            raise YouTubeError("OAuth state mismatch; start the connection again.")
        s = settings()
        resp = await self._http.post(TOKEN_URL, data={
            "code": code, "client_id": s.yt_client_id, "client_secret": s.yt_client_secret,
            "redirect_uri": s.yt_redirect_uri, "grant_type": "authorization_code"})
        if resp.status_code != 200:
            raise YouTubeError(_error_text(resp), resp.status_code)
        tok = resp.json()
        record = {
            "access_token": tok["access_token"],
            "refresh_token": tok.get("refresh_token") or stored.get("refresh_token"),
            "expires_at": db.iso(db.utcnow() + timedelta(seconds=int(tok.get("expires_in", 3600)) - 60)),
            "scope": tok.get("scope"),
            "state": None,
        }
        _save_token(record)
        me = await self._authed("GET", f"{DATA_API}/channels", params={"part": "snippet", "mine": "true"})
        quota.record(quota.LIST_COST, "channels.list(mine)")
        items = me.json().get("items") or []
        if items:
            _save_token({"channel_id": items[0]["id"],
                         "channel_title": items[0].get("snippet", {}).get("title")})
        return connection_status()

    async def _access_token(self) -> str:
        tok = db.get("oauth_tokens", PROVIDER, key="provider")
        if not tok or not tok.get("refresh_token"):
            raise YouTubeError("YouTube is not connected.", reauth=True)
        exp = db.parse_iso(tok.get("expires_at"))
        if tok.get("access_token") and exp and exp > db.utcnow():
            return tok["access_token"]
        s = settings()
        resp = await self._http.post(TOKEN_URL, data={
            "client_id": s.yt_client_id, "client_secret": s.yt_client_secret,
            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
        if resp.status_code != 200:
            raise YouTubeError(_error_text(resp), resp.status_code,
                               reauth=resp.status_code in (400, 401))
        data = resp.json()
        _save_token({
            "access_token": data["access_token"],
            "expires_at": db.iso(db.utcnow() + timedelta(seconds=int(data.get("expires_in", 3600)) - 60)),
        })
        return data["access_token"]

    async def _authed(self, method: str, url: str, **kw) -> httpx.Response:
        token = await self._access_token()
        headers = {**kw.pop("headers", {}), "Authorization": f"Bearer {token}"}
        resp = await self._http.request(method, url, headers=headers, **kw)
        if resp.status_code == 401:
            raise YouTubeError("YouTube rejected the token; reconnect.", 401, reauth=True)
        return resp

    # ---- upload ----------------------------------------------------------- #
    async def upload(self, file_path: str, title: str, description: str,
                     tags: list[str], privacy: str, category_id: str) -> str:
        s = settings()
        if not quota.can_spend(s.yt_upload_cost):
            raise YouTubeError("Daily Data API quota would be exceeded.")
        size = os.path.getsize(file_path)
        body = {
            "snippet": {
                "title": (title or "Untitled")[:100],
                "description": (description or "")[:5000],
                "tags": _clean_tags(tags),
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": False,
            },
        }
        init = await self._authed(
            "POST", UPLOAD_API,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={"X-Upload-Content-Type": "video/mp4",
                     "X-Upload-Content-Length": str(size),
                     "Content-Type": "application/json; charset=UTF-8"},
            json=body)
        if init.status_code not in (200, 201) or "location" not in init.headers:
            raise YouTubeError(_error_text(init), init.status_code)
        # Charge the quota once the session is accepted: YouTube bills the insert.
        quota.record(s.yt_upload_cost, "videos.insert")
        session_url = init.headers["location"]

        offset = 0
        with open(file_path, "rb") as fh:
            while True:
                fh.seek(offset)
                chunk = fh.read(CHUNK)
                end = offset + len(chunk) - 1
                resp = await self._authed(
                    "PUT", session_url, content=chunk,
                    headers={"Content-Length": str(len(chunk)),
                             "Content-Range": f"bytes {offset}-{end}/{size}"})
                if resp.status_code in (200, 201):
                    return resp.json()["id"]
                if resp.status_code == 308:
                    rng = resp.headers.get("range")
                    offset = int(rng.split("-")[1]) + 1 if rng else 0
                    continue
                raise YouTubeError(_error_text(resp), resp.status_code)

    # ---- stats ------------------------------------------------------------ #
    async def video_stats(self, video_id: str) -> dict:
        resp = await self._authed("GET", f"{DATA_API}/videos",
                                  params={"part": "statistics,status", "id": video_id})
        quota.record(quota.LIST_COST, "videos.list(statistics)")
        if resp.status_code != 200:
            raise YouTubeError(_error_text(resp), resp.status_code)
        items = resp.json().get("items") or []
        if not items:
            return {}
        st = items[0].get("statistics", {})
        return {
            "views": _int_or_none(st.get("viewCount")),
            "likes": _int_or_none(st.get("likeCount")),
            "comments": _int_or_none(st.get("commentCount")),
            "privacy": items[0].get("status", {}).get("privacyStatus"),
        }

    async def video_analytics(self, video_id: str, published: datetime) -> dict:
        """Watch-time metrics; the Analytics API lags ~2 days, so this may be empty."""
        params = {
            "ids": "channel==MINE",
            "startDate": published.date().isoformat(),
            "endDate": db.utcnow().date().isoformat(),
            "metrics": "views,averageViewDuration,averageViewPercentage,subscribersGained",
            "filters": f"video=={video_id}",
        }
        resp = await self._authed("GET", ANALYTICS_API, params=params)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        rows = data.get("rows") or []
        if not rows:
            return {}
        names = [h["name"] for h in data.get("columnHeaders", [])]
        row = dict(zip(names, rows[0]))
        return {
            "avg_view_duration_s": row.get("averageViewDuration"),
            "avg_view_pct": row.get("averageViewPercentage"),
            "subscribers_gained": row.get("subscribersGained"),
        }


# --------------------------------------------------------------------------- #
def _save_token(values: dict) -> None:
    existing = db.get("oauth_tokens", PROVIDER, key="provider")
    if existing:
        db.update("oauth_tokens", PROVIDER, values, key="provider")
    else:
        db.insert("oauth_tokens", {"provider": PROVIDER, **values})


def connection_status() -> dict:
    tok = db.get("oauth_tokens", PROVIDER, key="provider") or {}
    s = settings()
    return {
        "configured": bool(s.yt_client_id and s.yt_client_secret),
        "api_key_set": bool(s.yt_api_key),
        "connected": bool(tok.get("refresh_token")),
        "channel_id": tok.get("channel_id"),
        "channel_title": tok.get("channel_title"),
        "app_verified": s.yt_app_verified,
        "upload_privacy": s.privacy,
    }


def disconnect() -> None:
    db.execute("DELETE FROM oauth_tokens WHERE provider = ?", (PROVIDER,))


def _clean_tags(tags) -> list[str]:
    """YouTube caps the combined tag length at 500 characters."""
    out, total = [], 0
    for t in tags or []:
        t = str(t).strip().lstrip("#")
        if not t or len(t) > 100:
            continue
        cost = len(t) + (2 if " " in t else 0) + (1 if out else 0)
        if total + cost > 500:
            break
        out.append(t)
        total += cost
    return out


def _int_or_none(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _error_text(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
        if isinstance(err, dict):
            return err.get("message") or str(err)
        if err:
            return f"{err}: {resp.json().get('error_description', '')}".strip(": ")
    except ValueError:
        pass
    return f"HTTP {resp.status_code}"
