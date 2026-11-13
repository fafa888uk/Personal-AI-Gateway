"""Tests for GET /api/v1/app/version (online-update info endpoint).

The endpoint is public (clients check for updates before login) and
server-side only: versions/download URLs/SHA-256 come from server config,
never from the client, and an unconfigured server honestly reports
configured=false instead of fake release data.
"""
from __future__ import annotations

import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))
sys.path.insert(0, os.path.dirname(__file__))

from gateway.config import Settings  # noqa: E402
from gateway.db import init_db  # noqa: E402
from gateway.main import create_app  # noqa: E402
from mock_upstream import MockUpstream  # noqa: E402


def _client_with_release(tmp_path, release_json, app_version=""):
    settings = Settings(
        openai_api_key="mock-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        database_url="",
        database_url_dev=f"sqlite:///{tmp_path}/test.db",
        admin_key="test-admin-key-123",
        candidate_models=["gpt-5.4-mini"],
        upstream_timeout_s=5.0,
        app_version=app_version,
        app_release_info_json=release_json,
    )
    app = create_app(settings, transport=MockUpstream().transport)
    app.state.session_factory = init_db(settings)
    app.state.rate_windows = {}
    app.state.semaphores = {}
    return TestClient(app)


RELEASE = {
    "version": "1.0.0",
    "platforms": {
        "ios": {"version": "1.0.0", "release_date": "2026-11-14",
                "download_url": "https://github.com/fafa920q-hue/Personal-AI-Gateway/releases/download/v1.0.0/PersonalAI-1.0.0-ios-unsigned.ipa",
                "sha256": "aa" * 32, "release_notes": "First test release."},
        "windows": {"version": "1.0.0", "release_date": "2026-11-14",
                    "download_url": "https://example.invalid/PersonalAI-1.0.0-windows.exe",
                    "sha256": "bb" * 32, "release_notes": "First test release."},
        "macos": {"version": "1.0.0", "release_date": "2026-11-14",
                  "download_url": "https://example.invalid/PersonalAI-1.0.0-macos.dmg",
                  "sha256": "cc" * 32, "release_notes": "First test release."},
        "web": {"version": "1.0.0", "release_date": "2026-11-14",
                "download_url": "https://ai.fafa888.uk",
                "sha256": None, "release_notes": "Refresh to load the new version."},
    },
}


def test_version_unconfigured(client):
    resp = client.get("/api/v1/app/version")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is False
    assert body["version"] is None
    assert body["platforms"] == {}


def test_version_configured(tmp_path):
    with _client_with_release(tmp_path, json.dumps(RELEASE), app_version="1.0.0") as c:
        resp = c.get("/api/v1/app/version")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["version"] == "1.0.0"
    assert body["gateway_version"] == "0.3.0"
    assert set(body["platforms"]) == {"ios", "windows", "macos", "web"}
    ios = body["platforms"]["ios"]
    assert ios["download_url"].endswith("PersonalAI-1.0.0-ios-unsigned.ipa")
    assert ios["sha256"] == "aa" * 32
    assert ios["release_notes"] == "First test release."


def test_version_invalid_json_is_not_a_500(tmp_path):
    with _client_with_release(tmp_path, "{not-json") as c:
        resp = c.get("/api/v1/app/version")
    assert resp.status_code == 200
    assert resp.json()["configured"] is False


def test_version_partial_entry_is_dropped(tmp_path):
    partial = {"version": "1.0.0", "platforms": {
        "ios": {"version": "1.0.0"},  # no download_url -> dropped
        "web": {"version": "1.0.0", "download_url": "https://ai.fafa888.uk"},
    }}
    with _client_with_release(tmp_path, json.dumps(partial)) as c:
        resp = c.get("/api/v1/app/version")
    body = resp.json()
    assert body["configured"] is True
    assert set(body["platforms"]) == {"web"}
