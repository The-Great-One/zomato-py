"""Secure, platform-independent local and browser geolocation."""

from __future__ import annotations

import json
import math
import os
import secrets
import tempfile
import threading
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse


class LocationError(Exception):
    """Base error for local location management."""


class LocationStorageError(LocationError):
    """Raised when persisted location data cannot be read or written safely."""


class LocationDetectionError(LocationError):
    """Raised when browser geolocation cannot produce an approved location."""


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class LocationRecord:
    """A user-approved geographic location suitable for persistence."""

    latitude: float
    longitude: float
    accuracy: float | None
    source: str
    approved_at: str

    def __post_init__(self) -> None:
        latitude = _finite_number("latitude", self.latitude)
        longitude = _finite_number("longitude", self.longitude)
        if not -90 <= latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")

        accuracy = self.accuracy
        if accuracy is not None:
            accuracy = _finite_number("accuracy", accuracy)
            if accuracy < 0:
                raise ValueError("accuracy must be nonnegative")

        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-empty string")
        if not isinstance(self.approved_at, str) or not self.approved_at.strip():
            raise ValueError("approved_at must be an ISO-8601 timestamp")
        try:
            approved_at = datetime.fromisoformat(self.approved_at)
        except ValueError as exc:
            raise ValueError("approved_at must be an ISO-8601 timestamp") from exc
        if approved_at.tzinfo is None:
            raise ValueError("approved_at must include a timezone")

        object.__setattr__(self, "latitude", latitude)
        object.__setattr__(self, "longitude", longitude)
        object.__setattr__(self, "accuracy", accuracy)
        object.__setattr__(self, "source", self.source.strip())

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON representation of this record."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> LocationRecord:
        """Validate and construct a record from decoded JSON."""
        if not isinstance(value, dict):
            raise ValueError("location data must be a JSON object")
        expected = {"latitude", "longitude", "accuracy", "source", "approved_at"}
        if set(value) != expected:
            raise ValueError("location data must contain exactly the approved location fields")
        return cls(**value)


class LocationStore:
    """Atomic private persistence for a single approved location."""

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        cache_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        if path is not None and cache_dir is not None:
            raise ValueError("provide path or cache_dir, not both")
        if path is not None:
            self.path = Path(path).expanduser()
        else:
            directory = Path(cache_dir).expanduser() if cache_dir is not None else Path.home() / ".zomato-py"
            self.path = directory / "location.json"

    def save(self, location: LocationRecord) -> None:
        """Persist a validated record via an atomic same-directory replace."""
        if not isinstance(location, LocationRecord):
            raise TypeError("location must be a LocationRecord")
        parent = self.path.parent
        temporary: Path | None = None
        try:
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name == "posix":
                os.chmod(parent, 0o700)
            payload = json.dumps(location.to_dict(), indent=2, sort_keys=True) + "\n"
            descriptor, name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=parent)
            temporary = Path(name)
            if os.name == "posix":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
            if os.name == "posix":
                os.chmod(self.path, 0o600)
        except OSError as exc:
            raise LocationStorageError(f"could not write location file {self.path}: {exc}") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def load(self) -> LocationRecord | None:
        """Load and validate the persisted record, or return None when absent."""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LocationStorageError(f"could not read location file {self.path}: {exc}") from exc
        try:
            return LocationRecord.from_dict(json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise LocationStorageError(f"invalid location file {self.path}: {exc}") from exc

    def clear(self) -> bool:
        """Remove the persisted location, returning whether it existed."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise LocationStorageError(f"could not clear location file {self.path}: {exc}") from exc
        return True


_HTML_TEMPLATE = """<!doctype html>
<meta charset=utf-8><title>Zomato location</title>
<p id=status>Approve browser location access to continue.</p>
<script>
const state = __STATE__;
const statusNode = document.getElementById('status');
const send = body => fetch('/callback', {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(Object.assign({state}, body))
}).then(() => { statusNode.textContent = 'Location received. You may close this tab.'; });
navigator.geolocation.getCurrentPosition(
  position => send({coordinates: {
    latitude: position.coords.latitude, longitude: position.coords.longitude,
    accuracy: position.coords.accuracy
  }}),
  error => send({error: {code: error.code}}),
  {enableHighAccuracy: false, timeout: 30000, maximumAge: 0}
);
</script>
"""


class _LocationCallbackHandler(BaseHTTPRequestHandler):
    server: _CallbackServer

    def log_message(self, _format: str, *_args: object) -> None:
        """Disable HTTP request logging so coordinates can never leak."""

    def _reply(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/callback":
            self._reply(405, "Method not allowed")
            return
        if parsed.path != "/":
            self._reply(404, "Not found")
            return
        if parse_qs(parsed.query).get("state") != [self.server.state]:
            self._reply(403, "Invalid state")
            return
        encoded = self.server.html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; connect-src 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/callback":
            self._reply(404, "Not found")
            return
        if not self.server.callback_lock.acquire(blocking=False):
            self._reply(409, "State callback already in progress")
            return
        try:
            self._handle_callback()
        finally:
            self.server.callback_lock.release()

    def _handle_callback(self) -> None:
        if self.server.used:
            self._reply(409, "State already used")
            return
        origin = self.headers.get("Origin")
        if origin != self.server.origin:
            self._reply(403, "Invalid origin")
            return
        if self.headers.get_content_type() != "application/json":
            self._reply(415, "Expected JSON")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._reply(400, "Invalid body length")
            return
        if length < 1:
            self._reply(400, "Empty body")
            return
        if length > self.server.max_body_bytes:
            self._reply(413, "Body too large")
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._reply(400, "Invalid JSON")
            return
        if not isinstance(payload, dict):
            self._reply(400, "Invalid payload")
            return
        success_fields = {"state", "coordinates"}
        error_fields = {"state", "error"}
        payload_fields = set(payload)
        if payload_fields not in (success_fields, error_fields):
            self._reply(400, "Invalid payload schema")
            return
        state = payload["state"]
        if not isinstance(state, str):
            self._reply(400, "Invalid state type")
            return
        if not secrets.compare_digest(state, self.server.state):
            self._reply(403, "Invalid state")
            return

        if payload_fields == error_fields:
            error = payload["error"]
            if not isinstance(error, dict) or set(error) != {"code"}:
                self._reply(400, "Invalid geolocation error")
                return
            code = error["code"]
            if type(code) is not int or code not in (1, 2, 3):
                self._reply(400, "Invalid geolocation error")
                return
            self.server.error_code = code
        else:
            coordinates = payload["coordinates"]
            if not isinstance(coordinates, dict):
                self._reply(400, "Invalid coordinates")
                return
            coordinate_fields = set(coordinates)
            required_coordinate_fields = {"latitude", "longitude"}
            if coordinate_fields not in (
                required_coordinate_fields,
                required_coordinate_fields | {"accuracy"},
            ):
                self._reply(400, "Invalid coordinates")
                return
            try:
                self.server.result = LocationRecord(
                    latitude=coordinates["latitude"],
                    longitude=coordinates["longitude"],
                    accuracy=coordinates.get("accuracy"),
                    source="browser",
                    approved_at=self.server.now(),
                )
            except (TypeError, ValueError):
                self._reply(400, "Invalid coordinates")
                return

        self.server.used = True
        self._reply(200, "Location callback accepted")
        self.server.completed.set()


class _CallbackServer(ThreadingHTTPServer):
    """Loopback-only one-shot callback server used by browser detection."""

    daemon_threads = True
    allow_reuse_address = False
    max_body_bytes = 4096

    def __init__(self, *, state: str, now: Callable[[], str] = _utc_now) -> None:
        self.state = state
        self.now = now
        self.used = False
        self.result: LocationRecord | None = None
        self.error_code: int | None = None
        self.completed = threading.Event()
        self.callback_lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), _LocationCallbackHandler)
        port = self.server_address[1]
        self.origin = f"http://127.0.0.1:{port}"
        self.html = _HTML_TEMPLATE.replace("__STATE__", json.dumps(state))

    def get_result(self) -> LocationRecord:
        """Return the approved result or raise its actionable browser error."""
        messages = {
            1: "Browser location permission was denied; allow location access and retry.",
            2: "Browser location is unavailable; check location services and retry.",
            3: "Browser location request timed out; retry and approve the prompt promptly.",
        }
        if self.error_code is not None:
            raise LocationDetectionError(messages[self.error_code])
        if self.result is None:
            raise LocationDetectionError("Browser location did not return coordinates.")
        return self.result


class BrowserLocationDetector:
    """Obtain explicit browser geolocation approval through a loopback callback."""

    def __init__(
        self,
        *,
        store: LocationStore | None = None,
        browser_open: Callable[[str], bool] = webbrowser.open,
        server_factory: Callable[..., _CallbackServer] = _CallbackServer,
    ) -> None:
        self.store = store or LocationStore()
        self.browser_open = browser_open
        self.server_factory = server_factory

    def detect(self, *, timeout: float = 60.0) -> LocationRecord:
        """Open the browser, await one approved callback, then persist it."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be a positive number")
        state = secrets.token_urlsafe(32)
        server = self.server_factory(state=state)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        serve_loop_started = False
        try:
            thread.start()
            serve_loop_started = True
            url = f"{server.origin}/?state={state}"
            try:
                opened = self.browser_open(url)
            except Exception as exc:
                raise LocationDetectionError(
                    "Could not open a web browser; open a browser session and retry."
                ) from exc
            if not opened:
                raise LocationDetectionError(
                    "Could not open a web browser; configure a default browser and retry."
                )
            if not server.completed.wait(float(timeout)):
                raise LocationDetectionError(
                    "Browser location detection timed out; retry and approve location access promptly."
                )
            location = server.get_result()
            self.store.save(location)
            return location
        finally:
            if serve_loop_started:
                try:
                    server.shutdown()
                finally:
                    server.server_close()
                thread.join(timeout=2)
            else:
                server.server_close()
