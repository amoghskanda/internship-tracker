"""SQLite state and run history for the scheduler."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence


class StateStore:
    """Store scheduler state in a small SQLite database.

    Reminder timestamps are written only by :meth:`record_reminded`, which the
    runner calls after its mail sender reports a successful delivery.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS daily_runs (
                    local_date TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    message TEXT
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    job_id TEXT PRIMARY KEY,
                    last_reminded TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    local_date TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT,
                    message TEXT
                );

                CREATE INDEX IF NOT EXISTS run_log_started_at
                    ON run_log(started_at);

                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def has_daily_success(self, local_date: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM daily_runs WHERE local_date = ? AND status = 'success'",
                (local_date,),
            ).fetchone()
        return row is not None

    def start_daily_attempt(self, local_date: str, started_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_runs(local_date, status, started_at, finished_at, message)
                VALUES (?, 'running', ?, NULL, NULL)
                ON CONFLICT(local_date) DO UPDATE SET
                    status = 'running',
                    started_at = excluded.started_at,
                    finished_at = NULL,
                    message = NULL
                """,
                (local_date, started_at),
            )

    def finish_daily_attempt(
        self, local_date: str, status: str, finished_at: str, message: str = ""
    ) -> None:
        if status not in {"success", "failure"}:
            raise ValueError("daily attempt status must be success or failure")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE daily_runs
                SET status = ?, finished_at = ?, message = ?
                WHERE local_date = ?
                """,
                (status, finished_at, message[:2000], local_date),
            )

    def start_log(self, kind: str, started_at: str, local_date: Optional[str] = None) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO run_log(kind, local_date, started_at, status)
                VALUES (?, ?, ?, 'running')
                """,
                (kind, local_date, started_at),
            )
            return int(cursor.lastrowid)

    def finish_log(self, run_id: int, status: str, finished_at: str, message: str = "") -> None:
        if status not in {"success", "failure", "skipped"}:
            raise ValueError("run log status must be success, failure, or skipped")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE run_log
                SET status = ?, finished_at = ?, message = ?
                WHERE id = ?
                """,
                (status, finished_at, message[:4000], run_id),
            )

    def get_last_reminded(self, job_id: str) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT last_reminded FROM reminders WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return None if row is None else str(row["last_reminded"])

    def get_last_reminded_many(self, job_ids: Sequence[str]) -> dict[str, str]:
        if not job_ids:
            return {}
        values: dict[str, str] = {}
        for start in range(0, len(job_ids), 900):
            chunk = tuple(job_ids[start : start + 900])
            placeholders = ",".join("?" for _ in chunk)
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT job_id, last_reminded FROM reminders WHERE job_id IN ({placeholders})",
                    chunk,
                ).fetchall()
            values.update(
                {str(row["job_id"]): str(row["last_reminded"]) for row in rows}
            )
        return values

    def record_reminded(self, job_ids: Iterable[str], reminded_at: str) -> None:
        ids = tuple(dict.fromkeys(str(job_id) for job_id in job_ids if str(job_id)))
        if not ids:
            return
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO reminders(job_id, last_reminded)
                VALUES (?, ?)
                ON CONFLICT(job_id) DO UPDATE SET last_reminded = excluded.last_reminded
                """,
                ((job_id, reminded_at) for job_id in ids),
            )

    def get_metadata(self, key: str) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row["value"])

    def set_metadata(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def recent_logs(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM run_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
