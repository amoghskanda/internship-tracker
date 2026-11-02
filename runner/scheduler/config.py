"""Configuration for the internship runner scheduler.

The scheduler uses a JSON file so the collector and workbook sync commands can
be changed without editing Python. Commands are argv arrays and never pass
through a shell.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import time, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_RECIPIENT = "your-email@example.com"
DEFAULT_TIMEZONE = "America/Los_Angeles"
DEFAULT_DAILY_TIME = "07:00"
DEFAULT_REMINDER_INTERVAL_HOURS = 12.0
DEFAULT_COMMAND_TIMEOUT_SECONDS = 900
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 8765


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _as_command(value: Any, name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be an argv array")
    command = tuple(str(part) for part in value)
    if any(not part for part in command):
        raise ValueError(f"{name} cannot contain empty arguments")
    return command


def _resolve_path(base: Path, value: Any, default: Path) -> Path:
    if value is None:
        return default
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _parse_daily_time(value: Any) -> time:
    text = str(value or DEFAULT_DAILY_TIME).strip()
    parts = text.split(":")
    if len(parts) not in (2, 3):
        raise ValueError("daily_run_time must use HH:MM or HH:MM:SS")
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError as exc:
        raise ValueError("daily_run_time must use HH:MM or HH:MM:SS") from exc
    try:
        return time(hour=hour, minute=minute, second=second)
    except ValueError as exc:
        raise ValueError("daily_run_time is outside the 24-hour clock") from exc


def _parse_timezone(value: Any) -> str:
    name = str(value or DEFAULT_TIMEZONE).strip()
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {name}") from exc
    return name


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"expected a boolean, got {value!r}")


@dataclass(frozen=True)
class SchedulerConfig:
    config_path: Optional[Path]
    root_dir: Path
    timezone_name: str
    daily_run_time: time
    reminder_interval: timedelta
    recipient_email: str
    data_dir: Path
    state_db_path: Path
    merged_json_path: Path
    workbook_path: Path
    dashboard_dir: Optional[Path]
    collector_command: Tuple[str, ...]
    rank_command: Tuple[str, ...]
    sync_command: Tuple[str, ...]
    read_command: Tuple[str, ...]
    update_command: Tuple[str, ...]
    command_timeout_seconds: int
    server_host: str
    server_port: int
    pending_statuses: Tuple[str, ...]
    smtp_host_env: str
    smtp_port_env: str
    smtp_username_env: str
    smtp_password_env: str
    smtp_from_env: str
    smtp_ssl: bool
    smtp_starttls: bool

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


def load_config(path: Optional[str | Path] = None) -> SchedulerConfig:
    """Load JSON configuration, falling back to safe local defaults.

    An absent config file is valid. It leaves the command arrays empty, which
    makes tick fail closed until the parent project supplies its commands.
    """

    package_root = Path(__file__).resolve().parents[1]
    requested = path or os.environ.get("INTERNSHIP_RUNNER_CONFIG")
    config_path: Optional[Path] = None
    raw: Mapping[str, Any] = {}
    if requested:
        config_path = Path(requested).expanduser().resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"config file does not exist: {config_path}")
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        raw = _as_mapping(loaded, "config")
        base_dir = config_path.parent
    else:
        default_path = package_root / "config.json"
        if default_path.exists():
            config_path = default_path
            with default_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            raw = _as_mapping(loaded, "config")
            base_dir = default_path.parent
        else:
            base_dir = package_root

    root_dir = _resolve_path(base_dir, raw.get("root_dir"), base_dir)
    data_dir = _resolve_path(root_dir, raw.get("data_dir"), root_dir / "data")
    default_state = data_dir / "scheduler.sqlite3"
    state_db_path = _resolve_path(root_dir, raw.get("state_db_path"), default_state)
    merged_json_value = raw.get("merged_json_path", raw.get("merged_jobs_path"))
    merged_json_path = _resolve_path(
        root_dir, merged_json_value, data_dir / "merged_jobs.json"
    )
    workbook_value = raw.get("workbook_path", raw.get("merged_workbook_path"))
    workbook_path = _resolve_path(root_dir, workbook_value, data_dir / "merged.xlsx")

    sibling_dashboard = root_dir.parent / "dashboard" / "dist" / "client"
    dashboard_default = sibling_dashboard if sibling_dashboard.exists() else root_dir / "dashboard"
    dashboard_value = raw.get("dashboard_dir", str(dashboard_default))
    dashboard_dir = (
        None
        if dashboard_value is None or str(dashboard_value).strip() == ""
        else _resolve_path(root_dir, dashboard_value, root_dir / "dashboard")
    )

    try:
        reminder_hours = float(
            raw.get("reminder_interval_hours", DEFAULT_REMINDER_INTERVAL_HOURS)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("reminder_interval_hours must be a number") from exc
    if reminder_hours <= 0:
        raise ValueError("reminder_interval_hours must be greater than zero")

    try:
        timeout_seconds = int(
            raw.get("command_timeout_seconds", DEFAULT_COMMAND_TIMEOUT_SECONDS)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("command_timeout_seconds must be an integer") from exc
    if timeout_seconds <= 0:
        raise ValueError("command_timeout_seconds must be greater than zero")

    server = _as_mapping(raw.get("server"), "server")
    try:
        server_port = int(server.get("port", raw.get("server_port", DEFAULT_SERVER_PORT)))
    except (TypeError, ValueError) as exc:
        raise ValueError("server port must be an integer") from exc
    if not 1 <= server_port <= 65535:
        raise ValueError("server port must be between 1 and 65535")

    pending_raw = raw.get("pending_statuses", ["Not applied"])
    if not isinstance(pending_raw, Sequence) or isinstance(pending_raw, (str, bytes)):
        raise ValueError("pending_statuses must be an array")
    pending_statuses = tuple(
        _normalise_status(str(status)) for status in pending_raw if str(status).strip()
    )
    if not pending_statuses:
        raise ValueError("pending_statuses must contain at least one value")

    smtp = _as_mapping(raw.get("smtp"), "smtp")
    recipient = str(raw.get("recipient_email", DEFAULT_RECIPIENT)).strip()
    if not recipient or "@" not in recipient:
        raise ValueError("recipient_email must contain an email address")

    return SchedulerConfig(
        config_path=config_path,
        root_dir=root_dir,
        timezone_name=_parse_timezone(raw.get("timezone", DEFAULT_TIMEZONE)),
        daily_run_time=_parse_daily_time(
            raw.get("daily_run_time", raw.get("daily_time", DEFAULT_DAILY_TIME))
        ),
        reminder_interval=timedelta(hours=reminder_hours),
        recipient_email=recipient,
        data_dir=data_dir,
        state_db_path=state_db_path,
        merged_json_path=merged_json_path,
        workbook_path=workbook_path,
        dashboard_dir=dashboard_dir,
        collector_command=_as_command(
            raw.get("collector_command"), "collector_command"
        ),
        rank_command=_as_command(
            raw.get("ranking_command", raw.get("rank_command")), "ranking_command"
        ),
        sync_command=_as_command(
            raw.get("excel_sync_command", raw.get("sync_command")),
            "excel_sync_command",
        ),
        read_command=_as_command(
            raw.get("excel_read_command", raw.get("read_command")),
            "excel_read_command",
        ),
        update_command=_as_command(
            raw.get("excel_update_command", raw.get("update_command")),
            "excel_update_command",
        ),
        command_timeout_seconds=timeout_seconds,
        server_host=str(
            server.get("host", raw.get("server_host", DEFAULT_SERVER_HOST))
        ),
        server_port=server_port,
        pending_statuses=pending_statuses,
        smtp_host_env=str(smtp.get("host_env", "SMTP_HOST")),
        smtp_port_env=str(smtp.get("port_env", "SMTP_PORT")),
        smtp_username_env=str(smtp.get("username_env", "SMTP_USERNAME")),
        smtp_password_env=str(smtp.get("password_env", "SMTP_PASSWORD")),
        smtp_from_env=str(smtp.get("from_env", "SMTP_FROM")),
        smtp_ssl=_parse_bool(smtp.get("ssl"), True),
        smtp_starttls=_parse_bool(smtp.get("starttls"), True),
    )


def _normalise_status(value: str) -> str:
    return " ".join(value.replace("_", " ").replace("-", " ").lower().split())
