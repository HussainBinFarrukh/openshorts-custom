"""Pipeline state machine, intake selection, pacing, quota and the YouTube calls.

YouTube is replaced by httpx.MockTransport; no network is used.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from pipeline import clips, config, db, intake, quota, scheduler, youtube

UTC = timezone.utc


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_DATA_DIR", str(tmp_path / "pipe"))
    monkeypatch.setenv("PIPELINE_TIMEZONE", "America/New_York")
    monkeypatch.setenv("PIPELINE_PUBLISH_WINDOW", "09:00-21:00")
    monkeypatch.setenv("PIPELINE_PUBLISH_MAX_PER_DAY", "3")
    monkeypatch.setenv("PIPELINE_PUBLISH_MIN_GAP_MINUTES", "180")
    monkeypatch.setenv("PIPELINE_YT_API_KEY", "test-key")
    monkeypatch.setenv("PIPELINE_YT_CLIENT_ID", "cid")
    monkeypatch.setenv("PIPELINE_YT_CLIENT_SECRET", "secret")
    db.init()
    return tmp_path


def _clip(status="pending_review", qa_passed=True, composed=None, **extra):
    cid = db.new_id()
    row = {
        "id": cid, "openshorts_job_id": db.new_id(), "clip_index": 0, "status": status,
        "title": "Why most founders hire too early", "description": "d", "tags": ["startups"],
        "raw_path": "/nonexistent.mp4", "composed_path": composed,
        "qa_report": {"passed": qa_passed, "checks": []},
        "created_at": db.iso(), "updated_at": db.iso(), **extra,
    }
    db.insert("clips", row)
    return cid


# --------------------------------------------------------------------------- #
# State machine + approval gate
# --------------------------------------------------------------------------- #
def test_illegal_transitions_are_refused(pipe):
    cid = _clip(status="draft")
    with pytest.raises(clips.TransitionError):
        clips.transition(cid, "approved")
    with pytest.raises(clips.TransitionError):
        clips.transition(cid, "published")
    assert clips.transition(cid, "shortlisted")["status"] == "shortlisted"


def test_unapproved_clip_cannot_be_scheduled(pipe):
    cid = _clip(status="pending_review")
    with pytest.raises(clips.TransitionError):
        scheduler.schedule(cid)


def test_approval_needs_qa_pass_and_a_reviewer(pipe):
    failed = _clip(qa_passed=False)
    with pytest.raises(clips.TransitionError):
        scheduler.approve(failed, "HBF")
    ok = _clip()
    with pytest.raises(clips.TransitionError):
        scheduler.approve(ok, "   ")
    now = datetime(2026, 10, 5, 13, 0, tzinfo=UTC)        # 09:00 New York
    row = scheduler.approve(ok, "HBF", now=now)
    assert row["status"] == "scheduled"
    assert row["approved_by"] == "HBF" and row["approved_at"]
    assert db.parse_iso(row["scheduled_for"]) >= now + timedelta(minutes=5)


# --------------------------------------------------------------------------- #
# Pacing
# --------------------------------------------------------------------------- #
def test_plan_slot_respects_window_gap_and_daily_cap(pipe):
    s = config.settings()
    ny = __import__("zoneinfo").ZoneInfo("America/New_York")
    # 23:30 New York: outside the window -> next day 09:00.
    now = datetime(2026, 10, 5, 23, 30, tzinfo=ny)
    slot = scheduler.plan_slot(now, [], s).astimezone(ny)
    assert (slot.day, slot.hour, slot.minute) == (6, 9, 0)

    # Gap: a slot at 09:00 pushes the next one to 12:00.
    taken = [datetime(2026, 10, 6, 9, 0, tzinfo=ny)]
    slot = scheduler.plan_slot(datetime(2026, 10, 6, 8, 0, tzinfo=ny), taken, s).astimezone(ny)
    assert (slot.hour, slot.minute) == (12, 0)

    # Daily cap: three taken that day -> next day.
    taken = [datetime(2026, 10, 6, h, 0, tzinfo=ny) for h in (9, 12, 15)]
    slot = scheduler.plan_slot(datetime(2026, 10, 6, 8, 0, tzinfo=ny), taken, s).astimezone(ny)
    assert (slot.day, slot.hour) == (7, 9)


def test_three_approvals_spread_across_the_day(pipe):
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)        # 08:00 New York
    slots = [db.parse_iso(scheduler.approve(_clip(), "HBF", now=now)["scheduled_for"])
             for _ in range(4)]
    gaps = [(b - a) for a, b in zip(slots, slots[1:])]
    assert all(g >= timedelta(minutes=180) for g in gaps)
    ny = __import__("zoneinfo").ZoneInfo("America/New_York")
    days = [s.astimezone(ny).date() for s in slots]
    assert days.count(days[0]) == 3 and days[3] > days[0]


# --------------------------------------------------------------------------- #
# Quota
# --------------------------------------------------------------------------- #
def test_quota_resets_on_pacific_midnight(pipe):
    late = datetime(2026, 10, 6, 6, 30, tzinfo=UTC)       # 23:30 Pacific, Oct 5
    quota.record(9000, "test", late)
    assert quota.remaining(late) == 1000
    assert not quota.can_spend(1600, late)
    after = datetime(2026, 10, 6, 7, 30, tzinfo=UTC)      # 00:30 Pacific, Oct 6
    assert quota.remaining(after) == 10000


# --------------------------------------------------------------------------- #
# Intake
# --------------------------------------------------------------------------- #
def test_parse_channel_input():
    assert youtube.parse_channel_input("https://www.youtube.com/@AlexHormozi") == {"forHandle": "@AlexHormozi"}
    assert youtube.parse_channel_input("@ycombinator") == {"forHandle": "@ycombinator"}
    cid = "UC" + "a" * 22
    assert youtube.parse_channel_input(f"https://youtube.com/channel/{cid}") == {"id": cid}
    with pytest.raises(ValueError):
        youtube.parse_channel_input("not a channel")


def test_parse_duration():
    assert youtube.parse_duration("PT1H2M3S") == 3723
    assert youtube.parse_duration("PT59S") == 59
    assert youtube.parse_duration("P1DT1S") == 86401
    assert youtube.parse_duration(None) is None


def test_pick_new_skips_back_catalogue_shorts_and_live(pipe):
    added = datetime(2026, 10, 1, tzinfo=UTC)
    now = datetime(2026, 10, 3, tzinfo=UTC)
    vids = [
        {"video_id": "old", "published_at": "2026-09-20T10:00:00Z", "duration_s": 3000, "privacy": "public"},
        {"video_id": "short", "published_at": "2026-10-02T10:00:00Z", "duration_s": 58, "privacy": "public"},
        {"video_id": "live", "published_at": "2026-10-02T11:00:00Z", "duration_s": 0, "live": "live", "privacy": "public"},
        {"video_id": "b", "published_at": "2026-10-02T12:00:00Z", "duration_s": 2400, "privacy": "public"},
        {"video_id": "a", "published_at": "2026-10-01T12:00:00Z", "duration_s": 1800, "privacy": "public"},
        {"video_id": "seen", "published_at": "2026-10-02T12:00:00Z", "duration_s": 2400, "privacy": "public"},
        {"video_id": "proc", "published_at": "2026-10-02T12:00:00Z", "duration_s": None, "privacy": "public"},
    ]
    take, skipped = intake.pick_new(vids, {"seen"}, added, now, timedelta(days=3), 180)
    assert [v["video_id"] for v in take] == ["a", "b"]           # oldest first
    assert {v["video_id"]: r for v, r in skipped} == {"short": "short_form", "live": "live"}


def _mock_youtube(handler_log, playlist_items, videos):
    def handler(request: httpx.Request):
        handler_log.append(request)
        path = request.url.path
        if path.endswith("/channels"):
            return httpx.Response(200, json={"items": [{
                "id": "UC" + "x" * 22, "snippet": {"title": "Test Channel"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UUxx"}}}]})
        if path.endswith("/playlistItems"):
            return httpx.Response(200, json={"items": [
                {"contentDetails": {"videoId": v}} for v in playlist_items]})
        if path.endswith("/videos"):
            ids = request.url.params["id"].split(",")
            return httpx.Response(200, json={"items": [videos[i] for i in ids if i in videos]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def _video(vid, published, seconds):
    return {"id": vid, "snippet": {"title": f"Video {vid}", "publishedAt": published,
                                   "liveBroadcastContent": "none"},
            "contentDetails": {"duration": f"PT{seconds}S"}, "status": {"privacyStatus": "public"}}


def test_add_watch_requires_permission_note(pipe):
    with pytest.raises(ValueError):
        asyncio.run(intake.add_watch("@someone", "  "))


def test_poll_submits_new_uploads_under_the_daily_limit(pipe, monkeypatch):
    monkeypatch.setenv("PIPELINE_INTAKE_DAILY_LIMIT", "1")
    log = []
    now = db.utcnow()
    published = db.iso(now - timedelta(hours=2))
    transport = _mock_youtube(log, ["v1", "v2", "s1"], {
        "v1": _video("v1", published, 2400),
        "v2": _video("v2", published, 1800),
        "s1": _video("s1", published, 45),
    })

    async def run():
        async with httpx.AsyncClient(transport=transport) as http:
            w = await intake.add_watch("@test", "Emailed permission from producer, 2026-09-30",
                                       client=youtube.YouTubeClient(http))
            db.update("watchlist", w["id"], {"added_at": db.iso(now - timedelta(days=1))})
            submitted = []

            async def submit(url, max_minutes):
                submitted.append((url, max_minutes))
                return f"job-{len(submitted)}"

            res = await intake.poll_once(submit, client=youtube.YouTubeClient(http), now=now)
            return res, submitted

    res, submitted = asyncio.run(run())
    assert res["submitted"] == 1 and res["skipped"] == 1
    assert len(submitted) == 1 and submitted[0][1] == 45
    assert all(r.url.params["key"] == "test-key" for r in log)
    rows = {r["youtube_video_id"]: r for r in db.query("SELECT * FROM source_videos")}
    assert rows["s1"]["status"] == "skipped" and rows["s1"]["skip_reason"] == "short_form"
    assert sum(1 for r in rows.values() if r["status"] == "processing") == 1
    # The video over the limit was not recorded, so a later tick can still take it.
    assert len(rows) == 2
    assert quota.used_today() >= 3


# --------------------------------------------------------------------------- #
# Clips from an OpenShorts job
# --------------------------------------------------------------------------- #
def test_register_job_clips_copies_files_and_is_idempotent(pipe):
    out = pipe / "output"
    (out / "job1").mkdir(parents=True)
    (out / "job1" / "a_clip_1.mp4").write_bytes(b"fake-mp4")
    job = {"status": "completed", "result": {"clips": [
        {"video_url": "/videos/job1/a_clip_1.mp4", "start": 10, "end": 42.5,
         "video_title_for_youtube_short": "Hiring too early kills startups",
         "video_description_for_instagram": "desc", "viral_hook_text": "Stop hiring"},
        {"video_url": "/videos/job1/missing.mp4", "start": 1, "end": 2},
    ]}}
    src = db.new_id()
    db.insert("source_videos", {"id": src, "url": "u", "status": "processing",
                                "openshorts_job_id": "job1", "created_at": db.iso(), "updated_at": db.iso()})
    created = clips.on_job_finished("job1", job, str(out))
    assert len(created) == 1
    c = created[0]
    assert c["status"] == "draft" and c["duration_s"] == 32.5 and c["source_video_id"] == src
    assert os.path.isfile(c["raw_path"]) and open(c["raw_path"], "rb").read() == b"fake-mp4"
    assert clips.on_job_finished("job1", job, str(out)) == []
    assert db.get("source_videos", src)["status"] == "completed"


def test_jobs_the_pipeline_did_not_submit_are_ignored(pipe):
    assert clips.on_job_finished("someone-elses-job", {"status": "completed"}, "output") == []


# --------------------------------------------------------------------------- #
# Publishing
# --------------------------------------------------------------------------- #
def _upload_transport(calls):
    def handler(request: httpx.Request):
        calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
        if request.method == "POST" and "upload/youtube" in str(request.url):
            return httpx.Response(200, headers={"Location": "https://upload.example/session/1"})
        if request.method == "PUT":
            rng = request.headers["content-range"]
            first, rest = rng.split(" ")[1].split("/")
            start, end = (int(x) for x in first.split("-"))
            if start == 0 and int(rest) > end + 1:
                return httpx.Response(308, headers={"Range": f"bytes=0-{end}"})
            return httpx.Response(200, json={"id": "YT123"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def _connect():
    db.insert("oauth_tokens", {"provider": "youtube", "access_token": "old",
                               "refresh_token": "r", "expires_at": db.iso(db.utcnow() - timedelta(minutes=1))})


def test_publish_due_uploads_privately_until_verified(pipe, monkeypatch):
    monkeypatch.setattr(youtube, "CHUNK", 1024)
    video = pipe / "composed.mp4"
    video.write_bytes(os.urandom(1500))
    cid = _clip(status="scheduled", composed=str(video),
                scheduled_for=db.iso(db.utcnow() - timedelta(minutes=1)))
    _connect()
    calls = []

    async def run():
        async with httpx.AsyncClient(transport=_upload_transport(calls)) as http:
            return await scheduler.publish_due(youtube.YouTubeClient(http))

    res = asyncio.run(run())
    assert res == {"published": 1, "failed": 0, "waiting_quota": 0}
    row = db.get("clips", cid)
    assert row["status"] == "published" and row["youtube_video_id"] == "YT123"
    init = next(c for c in calls if c.method == "POST" and "upload/youtube" in str(c.url))
    body = json.loads(init.content)
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["selfDeclaredMadeForKids"] is False
    assert init.headers["authorization"] == "Bearer fresh"          # token was refreshed
    puts = [c for c in calls if c.method == "PUT"]
    assert len(puts) == 2                                            # resumed after 308
    assert quota.used_today() == config.settings().yt_upload_cost


def test_publish_waits_when_quota_is_spent(pipe):
    video = pipe / "composed.mp4"
    video.write_bytes(b"x")
    cid = _clip(status="scheduled", composed=str(video),
                scheduled_for=db.iso(db.utcnow() - timedelta(minutes=1)))
    _connect()
    quota.record(9500, "earlier uploads")
    calls = []

    async def run():
        async with httpx.AsyncClient(transport=_upload_transport(calls)) as http:
            return await scheduler.publish_due(youtube.YouTubeClient(http))

    assert asyncio.run(run())["waiting_quota"] == 1
    assert db.get("clips", cid)["status"] == "scheduled"
    assert calls == []


def test_tags_are_cut_to_youtubes_500_character_limit():
    tags = [f"tag{i:03d}" + "x" * 40 for i in range(30)]
    kept = youtube._clean_tags(tags)
    assert sum(len(t) for t in kept) + len(kept) - 1 <= 500
    assert kept == tags[:len(kept)]


# --------------------------------------------------------------------------- #
# Analytics checkpoints
# --------------------------------------------------------------------------- #
def test_analytics_pulls_each_checkpoint_once(pipe):
    from pipeline import analytics

    published = db.utcnow() - timedelta(hours=80)
    cid = _clip(status="published", youtube_video_id="YT9", published_at=db.iso(published))
    _connect()

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if request.url.host == "youtubeanalytics.googleapis.com":
            return httpx.Response(200, json={
                "columnHeaders": [{"name": n} for n in (
                    "views", "averageViewDuration", "averageViewPercentage", "subscribersGained")],
                "rows": [[1200, 21.5, 64.0, 7]]})
        return httpx.Response(200, json={"items": [{
            "statistics": {"viewCount": "1300", "likeCount": "88", "commentCount": "9"},
            "status": {"privacyStatus": "public"}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await analytics.pull_due(youtube.YouTubeClient(http))

    assert asyncio.run(run()) == 2                      # 24h and 72h are due, 7d is not
    assert asyncio.run(run()) == 0                      # never pulled twice
    rows = {r["checkpoint"]: r for r in db.query("SELECT * FROM metrics WHERE clip_id = ?", (cid,))}
    assert set(rows) == {"24h", "72h"}
    assert rows["72h"]["views"] == 1300 and rows["72h"]["avg_view_pct"] == 64.0
    perf = analytics.performance()
    assert perf[0]["checkpoint"] == "72h" and perf[0]["subscribers_gained"] == 7
