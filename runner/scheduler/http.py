"""Local dashboard server with workbook-backed application updates."""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import unquote, urlsplit

from .config import SchedulerConfig
from .email import smtp_environment_configured
from .state import StateStore


class LocalServer:
    """Serve dashboard files and local workbook-backed data."""

    def __init__(self, config: SchedulerConfig, state: Optional[StateStore] = None):
        self.config = config
        self.state = state or StateStore(config.state_db_path)

    def serve_forever(self) -> None:
        handler = self._handler_class()
        server = ThreadingHTTPServer(
            (self.config.server_host, self.config.server_port), handler
        )
        server.daemon_threads = True
        try:
            server.serve_forever()
        finally:
            server.server_close()

    def _handler_class(self):
        config = self.config
        state = self.state
        workbook_update_lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            server_version = "InternshipRunner/1.0"

            def do_GET(self) -> None:  # noqa: N802
                if not _allowed_host(self.headers.get("Host")):
                    self._send_error(HTTPStatus.BAD_REQUEST, "Host must be localhost")
                    return
                parsed = urlsplit(self.path)
                route = unquote(parsed.path)
                if route == "/api/jobs":
                    self._serve_jobs()
                elif route == "/api/workbook":
                    self._serve_workbook()
                elif route == "/api/status":
                    self._serve_json(_status_payload(config, state))
                elif route.startswith("/api/"):
                    self._send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")
                else:
                    self._serve_static(route)

            def do_HEAD(self) -> None:  # noqa: N802
                if not _allowed_host(self.headers.get("Host")):
                    self._send_error(HTTPStatus.BAD_REQUEST, "Host must be localhost")
                    return
                self._send_error(HTTPStatus.METHOD_NOT_ALLOWED, "GET required")

            def do_POST(self) -> None:  # noqa: N802
                if not _allowed_host(self.headers.get("Host")):
                    self._send_error(HTTPStatus.BAD_REQUEST, "Host must be localhost")
                    return
                if urlsplit(self.path).path not in {"/api/application-status", "/api/applications"}:
                    self._send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")
                    return
                self._update_application()

            def do_PUT(self) -> None:  # noqa: N802
                self._send_error(HTTPStatus.METHOD_NOT_ALLOWED, "POST required")

            def do_DELETE(self) -> None:  # noqa: N802
                if not _allowed_host(self.headers.get("Host")):
                    self._send_error(HTTPStatus.BAD_REQUEST, "Host must be localhost")
                    return
                if urlsplit(self.path).path != "/api/applications":
                    self._send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")
                    return
                self._update_application(force_removed=True)

            def _serve_jobs(self) -> None:
                try:
                    with config.merged_json_path.open("r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                except FileNotFoundError:
                    self._send_error(HTTPStatus.NOT_FOUND, "Merged jobs JSON is not available")
                    return
                except (OSError, json.JSONDecodeError) as exc:
                    self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Cannot read jobs JSON: {exc}")
                    return
                if not isinstance(payload, (list, Mapping)):
                    self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Merged jobs JSON has an invalid shape")
                    return
                self._serve_json(payload)

            def _update_application(self, force_removed: bool = False) -> None:
                if not config.update_command:
                    self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Workbook updates are not configured")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_error(HTTPStatus.BAD_REQUEST, "Invalid content length")
                    return
                if length <= 0 or length > 8192:
                    self._send_error(HTTPStatus.BAD_REQUEST, "Request body must be JSON under 8 KB")
                    return
                try:
                    payload = json.loads(self.rfile.read(length))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_error(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON")
                    return
                job_id = str(payload.get("id", "")).strip() if isinstance(payload, Mapping) else ""
                if not job_id or len(job_id) > 512:
                    self._send_error(HTTPStatus.BAD_REQUEST, "A valid job id is required")
                    return
                status = str(payload.get("status", "")).strip() if isinstance(payload, Mapping) and "status" in payload else None
                allowed_statuses = {"Not applied", "Interested", "Applied", "OA", "Interviewing", "Offer", "Rejected", "Withdrawn"}
                if status is not None and status not in allowed_statuses:
                    self._send_error(HTTPStatus.BAD_REQUEST, "Unsupported application status")
                    return
                command = [*config.update_command, "--input", str(config.workbook_path), "--json-output", str(config.merged_json_path), "--id", job_id]
                if status is not None:
                    command.extend(("--status", status))
                for payload_key, flag in (("applied_date", "--applied-date"), ("deadline", "--deadline"), ("oa_date", "--oa-date"), ("interview_date", "--interview-date"), ("notes", "--notes"), ("manual_priority_override", "--priority-override")):
                    if isinstance(payload, Mapping) and payload_key in payload:
                        value = str(payload.get(payload_key) or "")
                        if payload_key == "manual_priority_override" and value not in {"", "Tier 1", "Tier 2", "Tier 3", "Tier 4"}:
                            self._send_error(HTTPStatus.BAD_REQUEST, "Unsupported priority override")
                            return
                        if len(value) > (4000 if payload_key == "notes" else 64):
                            self._send_error(HTTPStatus.BAD_REQUEST, f"{payload_key} is too long")
                            return
                        command.extend((flag, value))
                if force_removed or (isinstance(payload, Mapping) and "removed" in payload):
                    removed = True if force_removed else bool(payload.get("removed"))
                    command.extend(("--removed", "Yes" if removed else "No"))
                if status is None and len(command) == len(config.update_command) + 6:
                    self._send_error(HTTPStatus.BAD_REQUEST, "No application fields were supplied")
                    return
                try:
                    with workbook_update_lock:
                        completed = subprocess.run(
                            command,
                            cwd=config.root_dir,
                            capture_output=True,
                            text=True,
                            timeout=config.command_timeout_seconds,
                            check=False,
                        )
                except subprocess.TimeoutExpired:
                    self._send_error(HTTPStatus.GATEWAY_TIMEOUT, "Workbook update timed out")
                    return
                except OSError as exc:
                    self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Could not start workbook update: {exc}")
                    return
                if completed.returncode != 0:
                    detail = (completed.stderr or completed.stdout or "Workbook update failed").strip().splitlines()[-1]
                    self._send_error(HTTPStatus.CONFLICT, detail)
                    return
                self._serve_json({"id": job_id, "status": status, "removed": force_removed or bool(payload.get("removed", False)), "saved": True})

            def _serve_workbook(self) -> None:
                path = config.workbook_path
                try:
                    resolved = path.resolve(strict=True)
                    if not resolved.is_file():
                        raise FileNotFoundError
                    size = resolved.stat().st_size
                    modified = resolved.stat().st_mtime
                except FileNotFoundError:
                    self._send_error(HTTPStatus.NOT_FOUND, "Merged workbook is not available")
                    return
                except OSError as exc:
                    self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Cannot read workbook: {exc}")
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                self.send_header("Content-Length", str(size))
                self.send_header("Last-Modified", _http_date(modified))
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{_download_name(resolved.name)}"',
                )
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    with resolved.open("rb") as handle:
                        while True:
                            chunk = handle.read(1024 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def _serve_static(self, route: str) -> None:
                root = config.dashboard_dir
                if root is None or not root.exists():
                    self._send_error(HTTPStatus.NOT_FOUND, "Dashboard is not available")
                    return
                if route == "/":
                    route = "/index.html"
                elif not Path(route).suffix:
                    html_route = f"{route.rstrip('/')}.html"
                    route = html_route if (root / html_route.lstrip("/")).is_file() else f"{route.rstrip('/')}/index.html"
                relative = route.lstrip("/")
                if any(part.startswith(".") for part in Path(relative).parts):
                    self._send_error(HTTPStatus.NOT_FOUND, "File is not available")
                    return
                candidate = (root / relative).resolve()
                if not _inside(candidate, root.resolve()) or not candidate.is_file():
                    self._send_error(HTTPStatus.NOT_FOUND, "File is not available")
                    return
                try:
                    content = candidate.read_bytes()
                except OSError as exc:
                    self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Cannot read dashboard file: {exc}")
                    return
                content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(content)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def _serve_json(self, payload: Any) -> None:
                encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(encoded)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def _send_error(self, status: HTTPStatus, message: str) -> None:
                payload = json.dumps({"error": message}).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                # Keep the service quiet unless the caller enables HTTP logging.
                return

        return Handler


def _allowed_host(host_header: Optional[str]) -> bool:
    if not host_header:
        return False
    host = host_header.rsplit(":", 1)[0].strip("[]").lower()
    return host in {"localhost", "127.0.0.1"}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _http_date(timestamp: float) -> str:
    from email.utils import formatdate

    return formatdate(timestamp, usegmt=True)


def _download_name(name: str) -> str:
    cleaned = "".join(character for character in name if character.isalnum() or character in {".", "-", "_"})
    return cleaned or "workbook.xlsx"


def _status_payload(config: SchedulerConfig, state: StateStore) -> dict[str, Any]:
    logs = state.recent_logs(limit=100)
    last_collection = None
    last_sync = None
    last_error = None
    for row in logs:
        kind = str(row["kind"])
        if kind in {"daily", "collection"} and row["finished_at"] and last_collection is None:
            last_collection = row["finished_at"]
        if kind in {"daily", "sync"} and row["finished_at"] and last_sync is None:
            last_sync = row["finished_at"]
        if row["status"] == "failure" and last_error is None:
            last_error = row["message"] or "scheduler operation failed"
    return {
        "email_configured": smtp_environment_configured(config, _status_environment(config)),
        "last_collection": last_collection,
        "last_sync": last_sync,
        "last_error": last_error,
        "timezone": config.timezone_name,
        "daily_run_time": config.daily_run_time.strftime("%H:%M:%S"),
    }


def _status_environment(config: SchedulerConfig) -> dict[str, str]:
    """Read the small non-secret status inputs again for long-lived servers."""

    values = dict(os.environ)
    env_path = config.root_dir / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values.setdefault(key, value)
    return values
