"""Command line entry points for the scheduler service."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .config import SchedulerConfig, load_config
from .email import (
    EmailDeliveryError,
    EmailNotConfigured,
    SMTPEmailSender,
    smtp_environment_configured,
)
from .http import LocalServer
from .runner import Scheduler


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        _load_env_file(config.root_dir / ".env")
        if args.command == "tick":
            return _tick(config, args.now)
        if args.command == "serve":
            return _serve(config, args.host, args.port)
        if args.command == "setup-email":
            return _setup_email(config)
        if args.command == "config-check":
            return _config_check(config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"scheduler error: {exc}")
        return 2
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internship runner scheduler")
    parser.add_argument("--config", help="path to scheduler JSON config")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tick = subparsers.add_parser("tick", help="run one scheduled tick")
    tick.add_argument(
        "--now",
        help="override current time with an ISO-8601 value, for testing",
    )
    serve = subparsers.add_parser("serve", help="serve the local dashboard")
    serve.add_argument("--host", help="bind host, defaults to config")
    serve.add_argument("--port", type=int, help="bind port, defaults to config")
    subparsers.add_parser(
        "setup-email", help="save Gmail SMTP settings and send a test email"
    )
    subparsers.add_parser("config-check", help="validate config without sending mail")
    return parser


def _tick(config: SchedulerConfig, now_text: Optional[str]) -> int:
    now = _parse_now(now_text, config)
    result = Scheduler(config).run_tick(now)
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0


def _serve(config: SchedulerConfig, host: Optional[str], port: Optional[int]) -> int:
    if host or port:
        config = replace(
            config,
            server_host=host or config.server_host,
            server_port=port or config.server_port,
        )
    LocalServer(config).serve_forever()
    return 0


def _config_check(config: SchedulerConfig) -> int:
    print(
        json.dumps(
            {
                "config_path": str(config.config_path) if config.config_path else None,
                "root_dir": str(config.root_dir),
                "timezone": config.timezone_name,
                "daily_run_time": config.daily_run_time.strftime("%H:%M:%S"),
                "recipient_email": config.recipient_email,
                "collector_command_configured": bool(config.collector_command),
                "ranking_command_configured": bool(config.rank_command),
                "sync_command_configured": bool(config.sync_command),
                "read_command_configured": bool(config.read_command),
                "update_command_configured": bool(config.update_command),
                "email_configured": smtp_environment_configured(config),
                "dashboard_dir": str(config.dashboard_dir) if config.dashboard_dir else None,
            },
            sort_keys=True,
        )
    )
    return 0


def _setup_email(config: SchedulerConfig) -> int:
    address = input(f"Gmail address [{config.recipient_email}]: ").strip()
    address = address or config.recipient_email
    if "@" not in address:
        print("scheduler error: enter a valid Gmail address")
        return 2
    app_password = getpass.getpass("Gmail app password (input is hidden): ")
    app_password = "".join(app_password.split())
    if not app_password:
        print("scheduler error: an app password is required")
        return 2

    updates = {
        config.smtp_host_env: "smtp.gmail.com",
        config.smtp_port_env: "465",
        config.smtp_username_env: address,
        config.smtp_password_env: app_password,
        config.smtp_from_env: address,
        "SMTP_SETUP_CONFIRMED_AT": "",
    }
    env_path = config.root_dir / ".env"
    try:
        _update_env_file(env_path, updates)
        os.environ.update(updates)
        test_config = replace(
            config,
            recipient_email=address,
            smtp_ssl=True,
            smtp_starttls=False,
        )
        SMTPEmailSender(test_config, require_confirmation=False).send(
            "Internship tracker SMTP setup test",
            "The internship tracker SMTP setup test was delivered successfully.",
            [config.recipient_email],
        )
    except (OSError, EmailNotConfigured, EmailDeliveryError, ValueError) as exc:
        print(f"SMTP test failed: {exc}")
        return 1

    _update_env_file(
        env_path,
        {"SMTP_SETUP_CONFIRMED_AT": datetime.now(timezone.utc).isoformat()},
    )
    print(
        f"SMTP test email delivered to {config.recipient_email}. "
        f"Credentials are stored in {env_path}."
    )
    return 0


def _parse_now(value: Optional[str], config: SchedulerConfig) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=config.timezone)
    return parsed


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
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
            if key and key not in os.environ:
                os.environ[key] = value


def _update_env_file(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    if path.exists():
        existing = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    output: list[str] = []
    for line in existing:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    content = "\n".join(output) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".env.", dir=str(path.parent), text=True
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
