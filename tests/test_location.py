"""Tests for secure local and browser-based geolocation."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest
import zomato

from zomato.location import (
    BrowserLocationDetector,
    LocationDetectionError,
    LocationError,
    LocationRecord,
    LocationStorageError,
    LocationStore,
    _CallbackServer,
)


APPROVED_AT = "2026-08-01T12:00:00+00:00"
SAFE_LATITUDE = 12.25
SAFE_LONGITUDE = 34.5


def test_programmatic_location_api_is_exported_from_package_root():
    assert zomato.LocationRecord is LocationRecord
    assert zomato.LocationStore is LocationStore
    assert zomato.BrowserLocationDetector is BrowserLocationDetector
    assert zomato.LocationError is LocationError
    assert zomato.LocationStorageError is LocationStorageError
    assert zomato.LocationDetectionError is LocationDetectionError


def record(**changes):
    base = LocationRecord(
        latitude=SAFE_LATITUDE,
        longitude=SAFE_LONGITUDE,
        accuracy=25.0,
        source="manual",
        approved_at=APPROVED_AT,
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", 90.0001),
        ("latitude", -90.0001),
        ("longitude", 180.0001),
        ("longitude", -180.0001),
        ("latitude", float("nan")),
        ("longitude", float("inf")),
        ("accuracy", -0.1),
        ("accuracy", float("inf")),
        ("latitude", True),
    ],
)
def test_location_record_rejects_invalid_coordinates(field, value):
    with pytest.raises(ValueError, match=field):
        record(**{field: value})


def test_location_record_accepts_boundaries_and_optional_accuracy():
    location = record(latitude=-90, longitude=180, accuracy=None)
    assert location.latitude == -90.0
    assert location.longitude == 180.0
    assert location.accuracy is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("source", ""), ("source", 4), ("approved_at", "not-a-date"), ("approved_at", "")],
)
def test_location_record_rejects_invalid_metadata(field, value):
    with pytest.raises(ValueError, match=field):
        record(**{field: value})


def test_location_store_round_trip_and_private_permissions(tmp_path):
    path = tmp_path / "private" / "location.json"
    store = LocationStore(path=path)

    store.save(record())

    assert store.load() == record()
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o077 == 0


def test_location_store_uses_atomic_replace(tmp_path):
    path = tmp_path / "location.json"
    store = LocationStore(path=path)

    with patch("zomato.location.os.replace", wraps=os.replace) as atomic_replace:
        store.save(record())

    atomic_replace.assert_called_once()
    source, destination = atomic_replace.call_args.args
    assert destination == path
    assert source.parent == path.parent
    assert not source.exists()


def test_location_store_default_path_is_platform_independent(monkeypatch, tmp_path):
    monkeypatch.setattr("zomato.location.Path.home", lambda: tmp_path)
    assert LocationStore().path == tmp_path / ".zomato-py" / "location.json"
    assert LocationStore(cache_dir=tmp_path / "cache").path == tmp_path / "cache" / "location.json"


def test_location_store_clear_is_idempotent(tmp_path):
    store = LocationStore(path=tmp_path / "location.json")
    store.save(record())
    assert store.clear() is True
    assert store.load() is None
    assert store.clear() is False


@pytest.mark.parametrize("contents", ["{broken", "[]", '{"latitude": 1}'])
def test_location_store_reports_corrupt_or_invalid_data(tmp_path, contents):
    path = tmp_path / "location.json"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(LocationStorageError, match="location file"):
        LocationStore(path=path).load()


def _request(url, *, method="GET", payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode()
    request_headers = dict(headers or {})
    if payload is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def _running_callback_server():
    server = _CallbackServer(state="one-time-state", now=lambda: APPROVED_AT)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _callback_request(server, payload, *, headers=None):
    request_headers = {"Origin": server.origin}
    request_headers.update(headers or {})
    return _request(
        f"{server.origin}/callback",
        method="POST",
        payload=payload,
        headers=request_headers,
    )


def test_callback_server_binds_only_to_ipv4_loopback_on_ephemeral_port():
    server = _CallbackServer(state="one-time-state", now=lambda: APPROVED_AT)
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_address[1] > 0
    finally:
        server.server_close()


def test_callback_success_accepts_matching_origin_and_consumes_state():
    server, thread = _running_callback_server()
    try:
        origin = server.origin
        status, _ = _request(
            f"{origin}/callback",
            method="POST",
            payload={
                "state": "one-time-state",
                "coordinates": {
                    "latitude": SAFE_LATITUDE,
                    "longitude": SAFE_LONGITUDE,
                    "accuracy": 12,
                },
            },
            headers={"Content-Type": "application/json", "Origin": origin},
        )
        assert status == 200
        assert server.result == record(accuracy=12.0, source="browser")

        reused, _ = _request(
            f"{origin}/callback",
            method="POST",
            payload={"state": "one-time-state", "coordinates": {"latitude": 0, "longitude": 0}},
            headers={"Content-Type": "application/json", "Origin": origin},
        )
        assert reused == 409
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_callback_rejects_missing_origin_without_consuming_state():
    server, thread = _running_callback_server()
    try:
        payload = {
            "state": "one-time-state",
            "coordinates": {"latitude": SAFE_LATITUDE, "longitude": SAFE_LONGITUDE},
        }

        status, _ = _request(
            f"{server.origin}/callback", method="POST", payload=payload
        )

        assert status == 403
        assert server.used is False
        assert server.result is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_callback_rejects_wrong_state_origin_routes_method_and_oversized_body():
    server, thread = _running_callback_server()
    try:
        origin = server.origin
        payload = {"state": "wrong", "coordinates": {"latitude": 0, "longitude": 0}}
        assert _callback_request(server, payload)[0] == 403
        assert _request(
            f"{origin}/callback",
            method="POST",
            payload={"state": "one-time-state", "coordinates": {"latitude": 0, "longitude": 0}},
            headers={"Origin": "https://attacker.invalid", "Content-Type": "application/json"},
        )[0] == 403
        port = server.server_address[1]
        assert _request(
            f"{origin}/callback",
            method="POST",
            payload={"state": "one-time-state", "coordinates": {"latitude": 0, "longitude": 0}},
            headers={"Origin": f"http://localhost:{port}", "Content-Type": "application/json"},
        )[0] == 403
        assert _request(f"{origin}/not-callback", method="POST", payload=payload)[0] == 404
        assert _request(f"{origin}/callback")[0] == 405
        oversized = urllib.request.Request(
            f"{origin}/callback",
            data=b"x" * (server.max_body_bytes + 1),
            method="POST",
            headers={"Content-Type": "application/json", "Origin": origin},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(oversized, timeout=2)
        assert exc.value.code == 413
        assert server.result is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_callback_server_serializes_one_time_state_use():
    server, thread = _running_callback_server()
    try:
        server.callback_lock.acquire()
        try:
            status, _ = _request(
                f"{server.origin}/callback",
                method="POST",
                payload={
                    "state": "one-time-state",
                    "coordinates": {"latitude": 0, "longitude": 0},
                },
            )
        finally:
            server.callback_lock.release()
        assert status == 409
        assert server.result is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_callback_rejects_invalid_json_payload_and_coordinate_ranges():
    server, thread = _running_callback_server()
    try:
        origin = server.origin
        bad_json = urllib.request.Request(
            f"{origin}/callback",
            data=b"not-json",
            method="POST",
            headers={"Content-Type": "application/json", "Origin": origin},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(bad_json, timeout=2)
        assert exc.value.code == 400
        assert _callback_request(
            server,
            {
                "state": "one-time-state",
                "coordinates": {"latitude": 91, "longitude": SAFE_LONGITUDE},
            },
        )[0] == 400
        assert server.result is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    ("code", "message"),
    [(1, "denied"), (2, "unavailable"), (3, "timed out")],
)
def test_browser_error_callback_becomes_actionable_detection_error(code, message):
    server, thread = _running_callback_server()
    try:
        status, _ = _request(
            f"{server.origin}/callback",
            method="POST",
            payload={"state": "one-time-state", "error": {"code": code}},
            headers={"Origin": server.origin},
        )
        assert status == 200
        with pytest.raises(LocationDetectionError, match=message):
            server.get_result()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_browser_detector_persists_only_successful_approved_callback(tmp_path):
    store = LocationStore(path=tmp_path / "location.json")

    def browser_open(url):
        state = url.rsplit("state=", 1)[1]
        origin = url.split("/?", 1)[0]
        _request(
            f"{origin}/callback",
            method="POST",
            payload={
                "state": state,
                "coordinates": {"latitude": SAFE_LATITUDE, "longitude": SAFE_LONGITUDE},
            },
            headers={"Origin": origin, "Content-Type": "application/json"},
        )
        return True

    detected = BrowserLocationDetector(store=store, browser_open=browser_open).detect(timeout=2)

    assert detected.source == "browser"
    assert store.load() == detected


def test_browser_detector_open_failure_is_actionable_and_does_not_persist(tmp_path):
    store = LocationStore(path=tmp_path / "location.json")
    detector = BrowserLocationDetector(store=store, browser_open=lambda _url: False)

    with pytest.raises(LocationDetectionError, match="open.*browser"):
        detector.detect(timeout=0.1)

    assert store.load() is None


def test_browser_detector_timeout_is_actionable_and_does_not_persist(tmp_path):
    store = LocationStore(path=tmp_path / "location.json")
    detector = BrowserLocationDetector(store=store, browser_open=lambda _url: True)

    with pytest.raises(LocationDetectionError, match="timed out"):
        detector.detect(timeout=0.02)

    assert store.load() is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "state": "one-time-state",
            "coordinates": {"latitude": 1, "longitude": 2},
            "error": {"code": 1},
        },
        {
            "state": "one-time-state",
            "coordinates": {"latitude": 1, "longitude": 2},
            "unknown": "field",
        },
        {
            "state": "one-time-state",
            "coordinates": {"latitude": 1, "longitude": 2, "altitude": 3},
        },
        {"state": "one-time-state", "error": {"code": 1, "message": "denied"}},
        {"state": "one-time-state", "error": {"code": 1, "unknown": "field"}},
        {
            "state": "one-time-state",
            "coordinates": {"latitude": True, "longitude": 2},
        },
        {
            "state": "one-time-state",
            "coordinates": {"latitude": 1, "longitude": False},
        },
        {
            "state": "one-time-state",
            "coordinates": {"latitude": 1, "longitude": 2, "accuracy": True},
        },
        {"state": "one-time-state", "error": {"code": True}},
        {"state": "one-time-state", "error": {"code": 1.0}},
        {"state": "one-time-state", "error": {"code": "1"}},
        {"state": "one-time-state", "coordinates": []},
        {"state": "one-time-state", "error": []},
        {"state": "one-time-state", "coordinates": {"latitude": 1}},
        {"state": "one-time-state", "coordinates": {"longitude": 2}},
        {
            "state": "one-time-state",
            "coordinates": {"latitude": "1", "longitude": 2},
        },
        {
            "state": "one-time-state",
            "coordinates": {"latitude": 1, "longitude": None},
        },
        {
            "state": "one-time-state",
            "coordinates": {"latitude": 1, "longitude": 2, "accuracy": "3"},
        },
        [],
    ],
    ids=[
        "both-success-and-error",
        "unknown-top-level",
        "unknown-coordinate-field",
        "error-message-not-in-minimal-protocol",
        "unknown-error-field",
        "boolean-latitude",
        "boolean-longitude",
        "boolean-accuracy",
        "boolean-error-code",
        "float-error-code",
        "string-error-code",
        "coordinates-not-object",
        "error-not-object",
        "missing-longitude",
        "missing-latitude",
        "string-latitude",
        "null-longitude",
        "string-accuracy",
        "top-level-not-object",
    ],
)
def test_callback_rejects_payloads_outside_exact_schema_without_consuming_state(payload):
    server, thread = _running_callback_server()
    try:
        status, _ = _callback_request(server, payload)

        assert status == 400
        assert server.used is False
        assert server.result is None
        assert server.error_code is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_browser_detector_closes_server_socket_when_thread_start_raises(tmp_path):
    server = _CallbackServer(state="factory-state", now=lambda: APPROVED_AT)
    server_close = Mock(wraps=server.server_close)
    shutdown = Mock(wraps=server.shutdown)
    server.server_close = server_close
    server.shutdown = shutdown
    thread = Mock()
    thread.start.side_effect = RuntimeError("thread start failed")
    detector = BrowserLocationDetector(
        store=LocationStore(path=tmp_path / "location.json"),
        browser_open=lambda _url: True,
        server_factory=lambda **_kwargs: server,
    )

    with patch("zomato.location.threading.Thread", return_value=thread):
        with pytest.raises(RuntimeError, match="thread start failed"):
            detector.detect(timeout=0.1)

    server_close.assert_called_once_with()
    shutdown.assert_not_called()
    assert server.fileno() == -1
