"""SMTP delivery for reminder digests."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Iterable, Mapping, Optional, Sequence

from .config import SchedulerConfig


class EmailNotConfigured(RuntimeError):
    """Raised when the required SMTP environment is absent."""


class EmailDeliveryError(RuntimeError):
    """Raised when SMTP cannot deliver a message."""


class SMTPEmailSender:
    """Send mail using SMTP values supplied through environment variables."""

    def __init__(self, config: SchedulerConfig, require_confirmation: bool = True):
        self.config = config
        self.require_confirmation = require_confirmation

    def _settings(self) -> tuple[str, int, str | None, str | None, str]:
        host = os.environ.get(self.config.smtp_host_env, "").strip()
        if not host:
            raise EmailNotConfigured(
                f"set {self.config.smtp_host_env} before enabling reminder email"
            )
        if self.require_confirmation and not os.environ.get("SMTP_SETUP_CONFIRMED_AT", "").strip():
            raise EmailNotConfigured(
                "run `python -m scheduler setup-email` and deliver its test message before reminders"
            )
        port_text = os.environ.get(self.config.smtp_port_env, "587").strip()
        try:
            port = int(port_text)
        except ValueError as exc:
            raise EmailNotConfigured(
                f"{self.config.smtp_port_env} must contain an integer port"
            ) from exc
        username = os.environ.get(self.config.smtp_username_env)
        password = os.environ.get(self.config.smtp_password_env)
        if bool(username) != bool(password):
            raise EmailNotConfigured(
                f"set both {self.config.smtp_username_env} and "
                f"{self.config.smtp_password_env}, or leave both unset"
            )
        sender = os.environ.get(self.config.smtp_from_env, "").strip()
        if not sender:
            sender = username or self.config.recipient_email
        return host, port, username, password, sender

    def send(self, subject: str, body: str, recipients: Sequence[str]) -> None:
        host, port, username, password, sender = self._settings()
        message = EmailMessage()
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message.set_content(body)
        try:
            if self.config.smtp_ssl:
                with smtplib.SMTP_SSL(host, port, timeout=30) as client:
                    if username and password:
                        client.login(username, password)
                    client.send_message(message)
            else:
                with smtplib.SMTP(host, port, timeout=30) as client:
                    if self.config.smtp_starttls:
                        client.starttls()
                    if username and password:
                        client.login(username, password)
                    client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError(str(exc)) from exc


def smtp_environment_configured(
    config: SchedulerConfig, environment: Optional[Mapping[str, str]] = None
) -> bool:
    """Return whether the SMTP environment has enough values to send mail."""

    values = environment or os.environ
    host = values.get(config.smtp_host_env, "").strip()
    if not host:
        return False
    username = values.get(config.smtp_username_env)
    password = values.get(config.smtp_password_env)
    confirmed = values.get("SMTP_SETUP_CONFIRMED_AT", "").strip()
    return bool(confirmed) and (bool(username and password) or (not username and not password))


def build_digest(
    jobs: Iterable[Mapping[str, object]],
    recipient: str,
) -> tuple[str, str]:
    """Build a plain text digest and subject from normalized job records."""

    records = list(jobs)
    count = len(records)
    noun = "opening" if count == 1 else "openings"
    subject = f"Internship tracker: {count} Not applied {noun}"
    lines = [
        f"The internship tracker found {count} {noun} with status Not applied.",
        "",
    ]
    for index, job in enumerate(records, start=1):
        title = _value(job, "title", "role", "position", "name") or "Untitled opening"
        company = _value(job, "company", "employer", "organization")
        location = _value(job, "location", "locations")
        url = _value(job, "url", "link", "application_url", "apply_url")
        lines.append(f"{index}. {title}")
        if company:
            lines.append(f"   Company: {company}")
        if location:
            lines.append(f"   Location: {location}")
        if url:
            lines.append(f"   Link: {url}")
        lines.append("")
    lines.append(f"Recipient: {recipient}")
    return subject, "\n".join(lines)


def _value(job: Mapping[str, object], *names: str) -> str:
    normalized = {"".join(char for char in str(key).lower() if char.isalnum()): value for key, value in job.items()}
    for name in names:
        value = normalized.get("".join(char for char in name.lower() if char.isalnum()))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""
