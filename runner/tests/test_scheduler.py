import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scheduler.config import SchedulerConfig
from scheduler.email import EmailDeliveryError
from scheduler.runner import CommandResult, Scheduler, reminder_is_due
from scheduler.state import StateStore


class FakeCommandRunner:
    def __init__(self, outcomes=None, read_callback=None):
        self.outcomes = outcomes or {}
        self.read_callback = read_callback
        self.calls = []

    def run(self, command, label):
        self.calls.append((tuple(command), label))
        if label == "workbook read sync" and self.read_callback:
            self.read_callback()
        outcome = self.outcomes.get(label, True)
        if isinstance(outcome, list):
            outcome = outcome.pop(0) if outcome else True
        if isinstance(outcome, CommandResult):
            return outcome
        if outcome:
            return CommandResult(True, 0, "")
        return CommandResult(False, 1, f"{label} failed")


class FakeEmailSender:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def send(self, subject, body, recipients):
        self.calls.append((subject, body, tuple(recipients)))
        if self.fail:
            raise EmailDeliveryError("test SMTP failure")


def build_config(root):
    data_dir = root / "data"
    data_dir.mkdir()
    return SchedulerConfig(
        config_path=None,
        root_dir=root,
        timezone_name="America/Los_Angeles",
        daily_run_time=time(7, 0),
        reminder_interval=timedelta(hours=12),
        recipient_email="candidate@example.com",
        data_dir=data_dir,
        state_db_path=data_dir / "state.sqlite3",
        merged_json_path=data_dir / "merged_jobs.json",
        workbook_path=data_dir / "internships.xlsx",
        dashboard_dir=None,
        collector_command=("collector",),
        rank_command=(),
        sync_command=("sync",),
        read_command=("read",),
        update_command=("update",),
        command_timeout_seconds=30,
        server_host="127.0.0.1",
        server_port=8765,
        pending_statuses=("not applied",),
        smtp_host_env="SMTP_HOST",
        smtp_port_env="SMTP_PORT",
        smtp_username_env="SMTP_USERNAME",
        smtp_password_env="SMTP_PASSWORD",
        smtp_from_env="SMTP_FROM",
        smtp_ssl=True,
        smtp_starttls=True,
    )


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config = build_config(self.root)
        self.config.workbook_path.write_bytes(b"workbook")
        self.config.merged_json_path.write_text("[]\n", encoding="utf-8")
        self.state = StateStore(self.config.state_db_path)
        self.zone = ZoneInfo(self.config.timezone_name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def mark_fresh(self):
        stat = self.config.workbook_path.stat()
        self.state.set_metadata("workbook_signature", f"{stat.st_mtime_ns}:{stat.st_size}")

    def mark_daily_success(self, local_now):
        local_date = local_now.date().isoformat()
        stamp = local_now.astimezone(timezone.utc).isoformat()
        self.state.start_daily_attempt(local_date, stamp)
        self.state.finish_daily_attempt(local_date, "success", stamp)

    def write_jobs(self, jobs):
        self.config.merged_json_path.write_text(json.dumps(jobs), encoding="utf-8")

    def test_daily_due_uses_local_time_across_dst(self):
        scheduler = Scheduler(self.config, state=self.state)
        before_spring = datetime(2026, 3, 8, 6, 59, tzinfo=self.zone)
        after_spring = datetime(2026, 3, 8, 7, 0, tzinfo=self.zone)
        self.assertFalse(scheduler._daily_is_due(before_spring))
        self.assertTrue(scheduler._daily_is_due(after_spring))

        self.mark_daily_success(after_spring)
        self.assertFalse(scheduler._daily_is_due(after_spring.replace(hour=8)))

        before_fall = datetime(2026, 11, 1, 6, 59, tzinfo=self.zone)
        after_fall = datetime(2026, 11, 1, 7, 0, tzinfo=self.zone)
        self.assertFalse(scheduler._daily_is_due(before_fall))
        self.assertTrue(scheduler._daily_is_due(after_fall))

    def test_reminder_waits_twelve_hours_after_discovery_then_repeats(self):
        now = datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)
        discovered = "2026-03-02T00:00:00+00:00"
        interval = timedelta(hours=12)
        self.assertFalse(reminder_is_due(None, discovered, now - timedelta(seconds=1), interval, self.zone))
        self.assertTrue(reminder_is_due(None, discovered, now, interval, self.zone))
        last = now.isoformat()
        self.assertFalse(reminder_is_due(last, discovered, now + timedelta(hours=11, minutes=59), interval, self.zone))
        self.assertTrue(reminder_is_due(last, discovered, now + interval, interval, self.zone))

    def test_failed_email_does_not_record_last_reminded(self):
        now = datetime(2026, 3, 2, 12, 0, tzinfo=self.zone)
        self.mark_daily_success(now)
        self.mark_fresh()
        self.write_jobs(
            [
                {
                    "id": "job-1",
                    "role": "Software intern",
                    "company": "Example",
                    "status": "Not applied",
                    "discovered_at": "2026-03-01T00:00:00Z",
                }
            ]
        )
        email = FakeEmailSender(fail=True)
        scheduler = Scheduler(
            self.config,
            state=self.state,
            command_runner=FakeCommandRunner(),
            email_sender=email,
        )
        result = scheduler.run_tick(now)
        retry = scheduler.run_tick(now + timedelta(minutes=15))
        self.assertTrue(result.reminder_attempted)
        self.assertFalse(result.reminder_sent)
        self.assertTrue(retry.reminder_attempted)
        self.assertEqual(len(email.calls), 2)
        self.assertIsNone(self.state.get_last_reminded("job-1"))

    def test_writer_failure_reuses_successful_collection_on_retry(self):
        now = datetime(2026, 3, 2, 8, 0, tzinfo=self.zone)
        self.config.merged_json_path.write_text("[]\n", encoding="utf-8")
        commands = FakeCommandRunner(outcomes={"workbook sync": [False, True]})
        scheduler = Scheduler(
            self.config,
            state=self.state,
            command_runner=commands,
            email_sender=FakeEmailSender(),
        )
        first = scheduler.run_tick(now)
        second = scheduler.run_tick(now + timedelta(minutes=1))
        labels = [label for _, label in commands.calls]
        self.assertFalse(first.daily_succeeded)
        self.assertTrue(second.daily_succeeded)
        self.assertEqual(labels.count("collector"), 1)
        self.assertEqual(labels.count("workbook sync"), 2)
        self.assertEqual(
            self.state.get_metadata("collection_success_date"), now.date().isoformat()
        )

    def test_failed_collector_waits_before_retrying(self):
        now = datetime(2026, 3, 2, 8, 0, tzinfo=self.zone)
        commands = FakeCommandRunner(outcomes={"collector": [False, True]})
        scheduler = Scheduler(
            self.config,
            state=self.state,
            command_runner=commands,
            email_sender=FakeEmailSender(),
        )
        first = scheduler.run_tick(now)
        second = scheduler.run_tick(now + timedelta(minutes=1))
        third = scheduler.run_tick(now + timedelta(minutes=15))
        labels = [label for _, label in commands.calls]
        self.assertFalse(first.daily_succeeded)
        self.assertFalse(second.daily_attempted)
        self.assertTrue(third.daily_succeeded)
        self.assertEqual(labels.count("collector"), 2)

    def test_ranking_runs_between_collection_and_workbook_sync(self):
        now = datetime(2026, 3, 2, 8, 0, tzinfo=self.zone)
        self.config = replace(self.config, rank_command=("rank",))
        self.config.merged_json_path.write_text("[]\n", encoding="utf-8")
        commands = FakeCommandRunner()
        result = Scheduler(
            self.config,
            state=self.state,
            command_runner=commands,
            email_sender=FakeEmailSender(),
        ).run_tick(now)
        labels = [label for _, label in commands.calls]
        self.assertTrue(result.daily_succeeded)
        self.assertEqual(labels[:3], ["collector", "resume ranking", "workbook sync"])

    def test_ranking_failure_blocks_workbook_sync(self):
        now = datetime(2026, 3, 2, 8, 0, tzinfo=self.zone)
        self.config = replace(self.config, rank_command=("rank",))
        commands = FakeCommandRunner(outcomes={"resume ranking": False})
        result = Scheduler(
            self.config,
            state=self.state,
            command_runner=commands,
            email_sender=FakeEmailSender(),
        ).run_tick(now)
        labels = [label for _, label in commands.calls]
        self.assertFalse(result.daily_succeeded)
        self.assertIn("resume ranking", labels)
        self.assertNotIn("workbook sync", labels)

    def test_successful_digest_has_no_duplicate_before_twelve_hours(self):
        now = datetime(2026, 3, 2, 12, 0, tzinfo=self.zone)
        self.mark_daily_success(now)
        self.mark_fresh()
        self.write_jobs(
            [
                {
                    "id": "job-1",
                    "role": "Software intern",
                    "company": "Example",
                    "status": "Not applied",
                    "discovered_at": "2026-03-01T00:00:00Z",
                }
            ]
        )
        email = FakeEmailSender()
        scheduler = Scheduler(
            self.config,
            state=self.state,
            command_runner=FakeCommandRunner(),
            email_sender=email,
        )
        first = scheduler.run_tick(now)
        second = scheduler.run_tick(now + timedelta(hours=1))
        self.assertTrue(first.reminder_sent)
        self.assertFalse(second.reminder_attempted)
        self.assertEqual(len(email.calls), 1)

    def test_failed_fresh_workbook_read_never_uses_stale_status(self):
        now = datetime(2026, 3, 2, 12, 0, tzinfo=self.zone)
        self.mark_daily_success(now)
        self.write_jobs(
            [
                {
                    "id": "job-1",
                    "role": "Software intern",
                    "status": "Not applied",
                    "discovered_at": "2026-03-01T00:00:00Z",
                }
            ]
        )
        commands = FakeCommandRunner(outcomes={"workbook read sync": False})
        email = FakeEmailSender()
        result = Scheduler(
            self.config,
            state=self.state,
            command_runner=commands,
            email_sender=email,
        ).run_tick(now)
        self.assertFalse(result.reminder_attempted)
        self.assertEqual(email.calls, [])
        self.assertIsNone(self.state.get_last_reminded("job-1"))

    def test_rows_with_applied_date_or_inactive_flag_are_skipped(self):
        now = datetime(2026, 3, 2, 12, 0, tzinfo=self.zone)
        self.mark_daily_success(now)
        self.mark_fresh()
        self.write_jobs(
            [
                {"id": "applied", "status": "Not applied", "applied_date": "2026-03-01", "discovered_at": "2026-02-01T00:00:00Z"},
                {"id": "inactive", "status": "Not applied", "active": False, "discovered_at": "2026-02-01T00:00:00Z"},
                {"id": "closed", "status": "Closed", "discovered_at": "2026-02-01T00:00:00Z"},
                {"id": "removed", "status": "Not applied", "removed": "Yes", "discovered_at": "2026-02-01T00:00:00Z"},
            ]
        )
        email = FakeEmailSender()
        result = Scheduler(
            self.config,
            state=self.state,
            command_runner=FakeCommandRunner(),
            email_sender=email,
        ).run_tick(now)
        self.assertFalse(result.reminder_attempted)
        self.assertEqual(email.calls, [])


if __name__ == "__main__":
    unittest.main()
