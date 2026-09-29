"""The /api/pipeline HTTP layer as wired into app.py (self-host mode)."""
import pytest
from fastapi.testclient import TestClient

import app as app_module
from pipeline import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_DATA_DIR", str(tmp_path / "pipe"))
    monkeypatch.setenv("PIPELINE_ENABLED", "0")
    db.init()
    with TestClient(app_module.app) as c:
        yield c


def _clip(status, qa_passed=True):
    cid = db.new_id()
    db.insert("clips", {"id": cid, "openshorts_job_id": db.new_id(), "clip_index": 0,
                        "status": status, "title": "t", "raw_path": "/x.mp4",
                        "qa_report": {"passed": qa_passed, "checks": []},
                        "created_at": db.iso(), "updated_at": db.iso()})
    return cid


def test_overview_and_listing(client):
    _clip("draft")
    r = client.get("/api/pipeline/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"] == {"draft": 1}
    assert body["youtube"]["upload_privacy"] == "private"
    assert len(client.get("/api/pipeline/clips?status=draft").json()["clips"]) == 1


def test_admin_token_is_enforced_when_set(client, monkeypatch):
    monkeypatch.setenv("PIPELINE_ADMIN_TOKEN", "s3cret")
    assert client.get("/api/pipeline/overview").status_code == 401
    assert client.get("/api/pipeline/overview", headers={"X-Pipeline-Token": "s3cret"}).status_code == 200
    assert client.get("/api/pipeline/overview?token=s3cret").status_code == 200


def test_approve_is_refused_without_qa_and_without_reviewer(client):
    bad = _clip("pending_review", qa_passed=False)
    r = client.post(f"/api/pipeline/clips/{bad}/action", json={"action": "approve", "reviewer": "HBF"})
    assert r.status_code == 400 and "QA" in r.json()["detail"]
    ok = _clip("pending_review")
    r = client.post(f"/api/pipeline/clips/{ok}/action", json={"action": "approve"})
    assert r.status_code == 400
    r = client.post(f"/api/pipeline/clips/{ok}/action", json={"action": "approve", "reviewer": "HBF"})
    assert r.status_code == 200 and r.json()["status"] == "scheduled"


def test_metadata_validation(client):
    cid = _clip("pending_review")
    assert client.patch(f"/api/pipeline/clips/{cid}", json={"title": "x" * 101}).status_code == 400
    assert client.patch(f"/api/pipeline/clips/{cid}", json={"layout": "sideways"}).status_code == 400
    r = client.patch(f"/api/pipeline/clips/{cid}", json={"title": "New title", "tags": ["a", " ", "b"]})
    assert r.status_code == 200 and r.json()["tags"] == ["a", "b"]


def test_watchlist_requires_permission_note(client):
    r = client.post("/api/pipeline/watchlist", json={"channel": "@someone", "permission_note": " "})
    assert r.status_code == 400


def test_media_is_confined_to_the_data_dir(client, tmp_path):
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"x")
    cid = _clip("draft")
    db.update("clips", cid, {"raw_path": str(outside)})
    assert client.get(f"/api/pipeline/media/raw/{cid}").status_code == 404
    assert client.get("/api/pipeline/media/other/abc").status_code == 404


def test_oauth_callback_rejects_a_forged_state(client):
    r = client.get("/api/pipeline/youtube/callback?code=abc&state=forged")
    assert r.status_code == 400
