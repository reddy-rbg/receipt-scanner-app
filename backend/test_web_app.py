"""The deployed website must be the shared Expo application, not the old demo."""

import os
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")

from main import app
import main


WEB_APP = Path(__file__).parent / "web_app"


def test_shared_expo_web_bundle_is_present():
    index = (WEB_APP / "index.html").read_text(encoding="utf-8")
    assert '<div id="root"></div>' in index
    assert "/_expo/static/js/web/entry-" in index
    assert list((WEB_APP / "_expo" / "static" / "js" / "web").glob("entry-*.js"))


def test_shared_scan_source_uses_browser_blob_uploads():
    source = (
        Path(__file__).parent.parent / "mobile" / "app" / "(tabs)" / "index.tsx"
    ).read_text(encoding="utf-8")
    assert "Platform.OS === 'web'" in source
    assert "await response.blob()" in source
    assert "formData.append(field, blob, name)" in source


def test_web_root_and_client_routes_use_the_shared_app():
    client = TestClient(app)
    root = client.get("/")
    client_route = client.get("/app/receipts")
    api = client.get("/api")

    assert root.status_code == 200
    assert client_route.status_code == 200
    assert '<div id="root"></div>' in root.text
    assert '<div id="root"></div>' in client_route.text
    assert api.status_code == 200
    assert api.json()["version"] == "1.0.3"


def test_backend_routes_keep_priority_over_spa_fallback():
    client = TestClient(app)
    assert client.get("/health/live").json()["status"] == "ok"
    assert '<script src="./app.js" defer></script>' in client.get("/ops/").text
    assert client.get("/receipts").status_code == 401


def test_client_errors_are_sanitized_and_recorded(monkeypatch):
    events = []
    monkeypatch.setattr(main, "record_error_event", lambda **event: events.append(event))
    client = TestClient(app)
    response = client.post(
        "/client-errors",
        json={
            "severity": "error",
            "source": "Scan",
            "message": "Receipt scan failed before completion",
            "error_type": "TypeError",
            "stack": "safe client stack",
            "metadata": {
                "action": "scan_receipt",
                "token": "must-not-be-stored",
                "nested": {"receipt": "must-not-be-stored"},
            },
        },
    )
    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert events[0]["source"] == "client_Scan"
    assert events[0]["metadata"]["token"] == "[redacted]"
    assert "nested" not in events[0]["metadata"]
    assert events[0]["metadata"]["client_error_type"] == "TypeError"
