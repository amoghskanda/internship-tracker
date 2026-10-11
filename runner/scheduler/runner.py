"""The daily collector, workbook sync, and reminder tick."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence

from .config import SchedulerConfig
from .email import EmailDeliveryError, EmailNotConfigured, SMTPEmailSender, build_digest
from .state import StateStore


LOGGER = logging.getLogger("internship_runner.scheduler")
UTC = timezone.utc
RETRY_BACKOFF = timedelta(minutes=15)


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    returncode: Optional[int]
    output: str


@dataclass(frozen=True)
class TickResult:
    daily_attempted: bool = False
    daily_succeeded: bool = False
    reminder_candidates: int = 0
    reminder_attempted: bool = False
    reminder_sent: bool = False
    skipped_reason: str = ""


class CommandRunner:
    """Run configured argv arrays without a shell."""

    def __init__(self, config: SchedulerConfig):
        self.config = config

    def run(self, command: Sequence[str], label: str) -> CommandResult:
        if not command:
            message = f"{label} command is empty"
            LOGGER.error(message)
            return CommandResult(False, None, message)
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH", "")
        pythonpath = str(self.config.root_dir)
        if existing_pythonpath:
            pythonpath = os.pathsep.join((pythonpath, existing_pythonpath))
        environment["PYTHONPATH"] = pythonpath
        LOGGER.info("running %s: %s", label, _display_command(command))
        try:
            completed = subprocess.run(
                list(command),
                cwd=str(self.config.root_dir),
                env=environment,
                capture_output=True,
                text=True,
                timeout=self.config.command_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = _command_output(exc.stdout, exc.stderr)
            message = f"{label} timed out after {self.config.command_timeout_seconds}s"
            LOGGER.error("%s%s", message, _log_suffix(output))
            return CommandResult(False, None, message + _log_suffix(output))
        except OSError as exc:
            message = f"could not start {label}: {exc}"
            LOGGER.error(message)
            return CommandResult(False, None, message)

        output = _command_output(completed.stdout, completed.stderr)
        if completed.returncode != 0:
            message = f"{label} exited with code {completed.returncode}"
            LOGGER.error("%s%s", message, _log_suffix(output))
            return CommandResult(False, completed.returncode, message + _log_suffix(output))
        LOGGER.info("%s completed%s", label, _log_suffix(output))
        return CommandResult(True, completed.returncode, output)


class AnotherTickRunning(RuntimeError):
    """Raised internally when launchd overlaps two ticks."""


class ProcessLock:
    """A non-blocking process lock backed by a file and fcntl."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._handle = None

    def __enter__(self) -> "ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+")
        try:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            self._handle.close()
            self._handle = None
            raise AnotherTickRunning from exc
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._handle is None:
            return
        try:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


class Scheduler:
    """Coordinate one launchd tick."""

    def __init__(
        self,
        config: SchedulerConfig,
        state: Optional[StateStore] = None,
        command_runner: Optional[CommandRunner] = None,
        email_sender: Optional[object] = None,
    ):
        self.config = config
        self.state = state or StateStore(config.state_db_path)
        self.command_runner = command_runner or CommandRunner(config)
        self.email_sender = email_sender or SMTPEmailSender(config)
        self.lock_path = config.data_dir / "scheduler.lock"

    def run_tick(self, now: Optional[datetime] = None) -> TickResult:
        current_utc = _as_utc(now or datetime.now(UTC), self.config.timezone)
        local_now = current_utc.astimezone(self.config.timezone)
        try:
            with ProcessLock(self.lock_path):
                return self._run_tick_locked(current_utc, local_now)
        except AnotherTickRunning:
            LOGGER.info("another scheduler tick is already running")
            return TickResult(skipped_reason="another tick is running")

    def _run_tick_locked(self, current_utc: datetime, local_now: datetime) -> TickResult:
        local_date = local_now.date().isoformat()
        daily_attempted = False
        daily_succeeded = False
        if self._daily_is_due(local_now, current_utc):
            daily_attempted = True
            daily_succeeded = self._run_daily(local_date, current_utc)
            if not daily_succeeded:
                return TickResult(
                    daily_attempted=True,
                    daily_succeeded=False,
                    skipped_reason="daily collection or workbook sync failed",
                )

        if not self._refresh_merged_json_if_needed(current_utc, local_date):
            return TickResult(
                daily_attempted=daily_attempted,
                daily_succeeded=daily_succeeded,
                skipped_reason="fresh workbook read failed",
            )

        candidates = self._read_due_jobs(current_utc)
        if not candidates:
            return TickResult(
                daily_attempted=daily_attempted,
                daily_succeeded=daily_succeeded,
                skipped_reason="no reminder is due",
            )

        subject, body = build_digest((job for _, job in candidates), self.config.recipient_email)
        LOGGER.info("sending reminder digest for %d opening(s)", len(candidates))
        if self._email_retry_blocked(current_utc):
            return TickResult(
                daily_attempted=daily_attempted,
                daily_succeeded=daily_succeeded,
                reminder_candidates=len(candidates),
                skipped_reason="email retry backoff is active",
            )
        reminder_run_id = self.state.start_log(
            "reminder", current_utc.isoformat(), local_date
        )
        try:
            self.email_sender.send(subject, body, [self.config.recipient_email])
        except (EmailNotConfigured, EmailDeliveryError) as exc:
            LOGGER.error("reminder email was not delivered: %s", exc)
            self.state.finish_log(
                reminder_run_id,
                "failure",
                datetime.now(UTC).isoformat(),
                str(exc),
            )
            self.state.set_metadata("email_failure_at", current_utc.isoformat())
            return TickResult(
                daily_attempted=daily_attempted,
                daily_succeeded=daily_succeeded,
                reminder_candidates=len(candidates),
                reminder_attempted=True,
                skipped_reason=str(exc),
            )
        except Exception as exc:  # pragma: no cover - guard unknown sender failures
            LOGGER.exception("reminder email failed")
            self.state.finish_log(
                reminder_run_id,
                "failure",
                datetime.now(UTC).isoformat(),
                f"reminder email failed: {exc}",
            )
            self.state.set_metadata("email_failure_at", current_utc.isoformat())
            return TickResult(
                daily_attempted=daily_attempted,
                daily_succeeded=daily_succeeded,
                reminder_candidates=len(candidates),
                reminder_attempted=True,
                skipped_reason=f"reminder email failed: {exc}",
            )

        sent_at = current_utc.isoformat()
        self.state.record_reminded((job_id for job_id, _ in candidates), sent_at)
        self.state.set_metadata("email_failure_at", "")
        self.state.finish_log(
            reminder_run_id,
            "success",
            datetime.now(UTC).isoformat(),
            f"sent {len(candidates)} opening(s)",
        )
        return TickResult(
            daily_attempted=daily_attempted,
            daily_succeeded=daily_succeeded,
            reminder_candidates=len(candidates),
            reminder_attempted=True,
            reminder_sent=True,
        )

    def _daily_is_due(
        self, local_now: datetime, current_utc: Optional[datetime] = None
    ) -> bool:
        if local_now.timetz().replace(tzinfo=None) < self.config.daily_run_time:
            return False
        local_date = local_now.date().isoformat()
        if self.state.has_daily_success(local_date):
            return False
        current_utc = current_utc or local_now.astimezone(UTC)
        return not self._collection_retry_blocked(local_date, current_utc)

    def _run_daily(self, local_date: str, current_utc: datetime) -> bool:
        started_at = current_utc.isoformat()
        self.state.start_daily_attempt(local_date, started_at)
        run_id = self.state.start_log("daily", started_at, local_date)
        collection_cached = self.state.get_metadata("collection_success_date") == local_date
        if collection_cached:
            LOGGER.info("reusing successful collection for %s", local_date)
        else:
            collector_result = self._run_logged_command(
                self.config.collector_command,
                "collector",
                "collection",
                current_utc,
                local_date,
            )
            if not collector_result.ok:
                message = collector_result.output or "collector failed"
                self.state.set_metadata("collection_failure_date", local_date)
                self.state.set_metadata("collection_failure_at", current_utc.isoformat())
                self.state.finish_daily_attempt(local_date, "failure", started_at, message)
                self.state.finish_log(run_id, "failure", started_at, message)
                return False
            self.state.set_metadata("collection_success_date", local_date)
            self.state.set_metadata("collection_failure_date", "")
            self.state.set_metadata("collection_failure_at", "")

        if self.config.rank_command:
            rank_result = self._run_logged_command(
                self.config.rank_command,
                "resume ranking",
                "ranking",
                current_utc,
                local_date,
            )
            if not rank_result.ok:
                message = rank_result.output or "resume ranking failed"
                self.state.finish_daily_attempt(local_date, "failure", started_at, message)
                self.state.finish_log(run_id, "failure", started_at, message)
                return False

        sync_result = self._run_logged_command(
            self.config.sync_command,
            "workbook sync",
            "sync",
            current_utc,
            local_date,
        )
        if not sync_result.ok:
            message = sync_result.output or "workbook sync failed"
            self.state.finish_daily_attempt(local_date, "failure", started_at, message)
            self.state.finish_log(run_id, "failure", started_at, message)
            return False

        finished_at = datetime.now(UTC).isoformat()
        self.state.finish_daily_attempt(local_date, "success", finished_at, "")
        self.state.finish_log(run_id, "success", finished_at, "")
        self._record_workbook_signature()
        return True

    def _collection_retry_blocked(self, local_date: str, current_utc: datetime) -> bool:
        if self.state.get_metadata("collection_failure_date") != local_date:
            return False
        failed_at = self.state.get_metadata("collection_failure_at")
        return _backoff_active(failed_at, current_utc)

    def _email_retry_blocked(self, current_utc: datetime) -> bool:
        return _backoff_active(self.state.get_metadata("email_failure_at"), current_utc)

    def _run_command(self, command: Sequence[str], label: str) -> CommandResult:
        return self.command_runner.run(command, label)

    def _run_logged_command(
        self,
        command: Sequence[str],
        label: str,
        kind: str,
        current_utc: datetime,
        local_date: str,
    ) -> CommandResult:
        started_at = current_utc.isoformat()
        run_id = self.state.start_log(kind, started_at, local_date)
        result = self._run_command(command, label)
        finished_at = datetime.now(UTC).isoformat()
        self.state.finish_log(
            run_id,
            "success" if result.ok else "failure",
            finished_at,
            result.output,
        )
        return result

    def _refresh_merged_json_if_needed(
        self, current_utc: datetime, local_date: str
    ) -> bool:
        try:
            signature = _workbook_signature(self.config.workbook_path)
        except OSError as exc:
            LOGGER.error("cannot inspect merged workbook: %s", exc)
            return False
        if signature is None:
            LOGGER.warning("merged workbook is not available; reminders are paused")
            return False
        previous = self.state.get_metadata("workbook_signature")
        if previous == signature and self.config.merged_json_path.exists():
            return True
        command = self.config.read_command or self.config.sync_command
        if not command:
            LOGGER.error(
                "workbook changed but no excel_read_command is configured; reminders are paused"
            )
            return False
        result = self._run_logged_command(
            command,
            "workbook read sync",
            "sync",
            current_utc,
            local_date,
        )
        if not result.ok:
            return False
        if not self.config.merged_json_path.exists():
            LOGGER.error("workbook read sync succeeded but did not write merged jobs JSON")
            return False
        self.state.set_metadata("workbook_signature", signature)
        return True

    def _record_workbook_signature(self) -> None:
        signature = _workbook_signature(self.config.workbook_path)
        if signature is not None:
            self.state.set_metadata("workbook_signature", signature)

    def _read_due_jobs(
        self, current_utc: datetime
    ) -> list[tuple[str, Mapping[str, object]]]:
        try:
            jobs = read_jobs_json(self.config.merged_json_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.error("cannot read merged jobs JSON: %s", exc)
            return []
        if not jobs:
            return []
        records: list[tuple[str, Mapping[str, object]]] = []
        ids: list[str] = []
        for job in jobs:
            if _has_applied_date(job) or _is_explicitly_inactive(job):
                continue
            job_id = job_identifier(job)
            if _job_status(job) not in self.config.pending_statuses:
                continue
            records.append((job_id, job))
            ids.append(job_id)
        if not records:
            return []
        previous = self.state.get_last_reminded_many(ids)
        due: list[tuple[str, Mapping[str, object]]] = []
        for job_id, job in records:
            if reminder_is_due(
                previous.get(job_id),
                _job_discovered_at(job),
                current_utc,
                self.config.reminder_interval,
                self.config.timezone,
            ):
                due.append((job_id, job))
        return due


def read_jobs_json(path: Path) -> list[Mapping[str, object]]:
    """Read the merged JSON file in either list or ``{"jobs": [...]}`` form."""

    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        jobs = payload
    elif isinstance(payload, Mapping):
        jobs = payload.get("jobs", payload.get("openings", []))
    else:
        raise ValueError("merged jobs JSON must be a list or object with jobs")
    if not isinstance(jobs, list):
        raise ValueError("merged jobs JSON jobs value must be an array")
    return [job for job in jobs if isinstance(job, Mapping)]


def job_identifier(job: Mapping[str, object]) -> str:
    for key in ("id", "job_id", "jobId", "opening_id", "openingId"):
        value = job.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    for key, value in job.items():
        normalized = _normalise_key(key)
        if normalized in {"id", "jobid", "openingid"} and str(value).strip():
            return str(value).strip()
    stable = {
        _normalise_key(str(key)): value
        for key, value in job.items()
        if _normalise_key(str(key))
        in {
            "title",
            "role",
            "position",
            "company",
            "employer",
            "organization",
            "url",
            "link",
            "location",
        }
    }
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str)
    return "job-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def reminder_is_due(
    last_reminded: Optional[str],
    discovered_at: Optional[str],
    now_utc: datetime,
    interval: timedelta,
    configured_zone,
) -> bool:
    if last_reminded:
        previous = _parse_source_timestamp(last_reminded, configured_zone)
        if previous is None:
            LOGGER.warning(
                "invalid last_reminded timestamp %r; retrying reminder", last_reminded
            )
            return True
        return now_utc >= previous + interval
    if not discovered_at:
        LOGGER.warning("pending opening has no discovered_at value; reminder is paused")
        return False
    discovered = _parse_source_timestamp(discovered_at, configured_zone)
    if discovered is None:
        LOGGER.warning("invalid discovered_at timestamp %r; reminder is paused", discovered_at)
        return False
    return now_utc >= discovered + interval


def _job_status(job: Mapping[str, object]) -> str:
    for key, value in job.items():
        if _normalise_key(str(key)) in {
            "status",
            "applicationstatus",
            "applicationstate",
            "applicationstatusvalue",
        }:
            return _normalise_status(str(value))
    return ""


def _has_applied_date(job: Mapping[str, object]) -> bool:
    for key, value in job.items():
        if _normalise_key(str(key)) in {"applieddate", "dateapplied"}:
            return bool(str(value).strip())
    return False


def _is_explicitly_inactive(job: Mapping[str, object]) -> bool:
    for key, value in job.items():
        normalized = _normalise_key(str(key))
        if normalized in {"removed", "hidden", "archived"} and str(value).strip().lower() in {"true", "1", "yes"}:
            return True
        if normalized in {"active", "isactive", "enabled"}:
            text = str(value).strip().lower()
            if text in {"false", "0", "no", "closed", "inactive", "disabled"}:
                return True
        if normalized in {"status", "applicationstatus", "applicationstate"}:
            if _normalise_status(str(value)) in {"closed", "inactive", "withdrawn"}:
                return True
    return False


def _job_discovered_at(job: Mapping[str, object]) -> Optional[str]:
    for key, value in job.items():
        if _normalise_key(str(key)) in {
            "discoveredat",
            "discovered",
            "datediscovered",
            "firstseen",
            "firstseenat",
        }:
            text = str(value).strip()
            if text:
                return text
    return None


def _parse_source_timestamp(value: str, configured_zone) -> Optional[datetime]:
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            parsed_date = date.fromisoformat(text)
            parsed = datetime.combine(parsed_date, time(hour=12), configured_zone)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=configured_zone)
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def _backoff_active(failed_at: Optional[str], current_utc: datetime) -> bool:
    if not failed_at:
        return False
    try:
        failed = datetime.fromisoformat(failed_at)
    except ValueError:
        return False
    if failed.tzinfo is None:
        failed = failed.replace(tzinfo=UTC)
    return current_utc < failed.astimezone(UTC) + RETRY_BACKOFF


def _workbook_signature(path: Path) -> Optional[str]:
    try:
        stat = Path(path).stat()
    except FileNotFoundError:
        return None
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _normalise_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _normalise_status(value: str) -> str:
    return " ".join(value.replace("_", " ").replace("-", " ").lower().split())


def _as_utc(value: datetime, configured_zone) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=configured_zone)
    return value.astimezone(UTC)


def _command_output(stdout: Any, stderr: Any) -> str:
    pieces = []
    for value in (stdout, stderr):
        if value:
            pieces.append(str(value).strip())
    return "\n".join(pieces)[-4000:]


def _log_suffix(output: str) -> str:
    return f": {output}" if output else ""


def _display_command(command: Sequence[str]) -> str:
    return " ".join(str(part) for part in command)
