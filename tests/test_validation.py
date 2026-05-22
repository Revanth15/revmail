from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import clear_settings_cache


RAW_KEY = "egw_live_test"
PEPPER = "test-pepper"
KEY_HASH = hashlib.sha256((RAW_KEY + PEPPER).encode("utf-8")).hexdigest()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    projects = [
        {
            "project_id": "bussing",
            "name": "BusSing",
            "api_key_hash": KEY_HASH,
            "default_from": "BusSing <alerts@example.com>",
            "allowed_from": ["BusSing <alerts@example.com>"],
            "allowed_templates": ["urgent_error", "status_update"],
            "allow_custom_html": False,
            "allowed_recipients": [],
            "daily_limit": 500,
            "minute_limit": 20,
        },
        {
            "project_id": "hackathon",
            "name": "Hackathon Projects",
            "api_key_hash": hashlib.sha256(("egw_live_hack" + PEPPER).encode("utf-8")).hexdigest(),
            "default_from": "Revanth Apps <hello@example.com>",
            "allowed_from": ["Revanth Apps <hello@example.com>"],
            "allowed_templates": ["urgent_error", "status_update", "custom"],
            "allow_custom_html": True,
            "allowed_recipients": ["user@example.com"],
            "daily_limit": 200,
            "minute_limit": 10,
        },
    ]
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("API_KEY_PEPPER", PEPPER)
    monkeypatch.setenv("PROJECTS_JSON", json.dumps(projects))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'email_gateway.db'}")
    clear_settings_cache()

    from app.main import app
    from app.database import init_db

    init_db()
    yield TestClient(app)
    clear_settings_cache()


def auth_headers(raw_key: str = RAW_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def test_rejects_missing_auth(client: TestClient):
    response = client.post("/v1/email/send", json={})
    assert response.status_code == 401


def test_rejects_too_many_recipients(client: TestClient):
    payload = {
        "project_id": "bussing",
        "template": "status_update",
        "to": [f"user{i}@example.com" for i in range(11)],
        "variables": {"app_name": "BusSing", "title": "Hi", "message": "Body", "timestamp": "now"},
    }
    response = client.post("/v1/email/send", json=payload, headers=auth_headers())
    assert response.status_code == 422


def test_rejects_custom_when_disabled(client: TestClient):
    payload = {
        "project_id": "bussing",
        "template": "custom",
        "to": ["admin@example.com"],
        "subject": "Hi",
        "html": "<p>Hello</p>",
    }
    response = client.post("/v1/email/send", json=payload, headers=auth_headers())
    assert response.status_code == 403


def test_rejects_disallowed_recipient(client: TestClient):
    payload = {
        "project_id": "hackathon",
        "template": "custom",
        "to": ["blocked@example.com"],
        "subject": "Hi",
        "html": "<p>Hello</p>",
    }
    response = client.post("/v1/email/send", json=payload, headers=auth_headers("egw_live_hack"))
    assert response.status_code == 403


def test_sends_and_deduplicates(client: TestClient):
    payload = {
        "project_id": "bussing",
        "template": "status_update",
        "to": ["admin@example.com"],
        "variables": {
            "app_name": "BusSing",
            "title": "Service restored",
            "message": "Back to normal.",
            "timestamp": "2026-05-23T12:30:00+08:00",
        },
        "idempotency_key": "status-1",
    }
    with patch("app.main.send_email", return_value="em_test_123") as mocked_send:
        first = client.post("/v1/email/send", json=payload, headers=auth_headers())
        second = client.post("/v1/email/send", json=payload, headers=auth_headers())

    assert first.status_code == 200
    assert first.json()["status"] == "sent"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["email_id"] == "em_test_123"
    assert mocked_send.call_count == 1


def test_logs_are_project_scoped(client: TestClient):
    response = client.get("/v1/email/logs", headers=auth_headers())
    assert response.status_code == 200
    assert "logs" in response.json()

