from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from mercurio.domain.models import (
    Assignment,
    Course,
    EventState,
    NotificationEvent,
    SubmissionState,
)

SCHEMA_VERSION = 1


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL
                );
                INSERT INTO schema_version(version)
                SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);

                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    google_subject TEXT,
                    timezone TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS course (
                    id INTEGER PRIMARY KEY,
                    google_course_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assignment (
                    id INTEGER PRIMARY KEY,
                    course_id INTEGER NOT NULL REFERENCES course(id),
                    google_work_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    due_utc TEXT,
                    due_date TEXT,
                    has_due_time INTEGER NOT NULL DEFAULT 0,
                    submission_state TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(course_id, google_work_id)
                );
                CREATE TABLE IF NOT EXISTS reminder_rule (
                    id INTEGER PRIMARY KEY,
                    antecedence_minutes INTEGER NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS notification_event (
                    id INTEGER PRIMARY KEY,
                    assignment_id INTEGER NOT NULL REFERENCES assignment(id),
                    milestone_minutes INTEGER NOT NULL,
                    due_utc TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    provider_id TEXT,
                    last_error TEXT,
                    UNIQUE(assignment_id, milestone_minutes, due_utc, channel)
                );
                CREATE TABLE IF NOT EXISTS sync_run (
                    id INTEGER PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    result TEXT NOT NULL,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS channel_consent (
                    channel TEXT PRIMARY KEY,
                    remote_id TEXT,
                    consent_version TEXT NOT NULL,
                    accepted_at TEXT,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_assignment_due ON assignment(due_utc);
                CREATE INDEX IF NOT EXISTS idx_event_state ON notification_event(state);
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(assignment)")}
            if "due_date" not in columns:
                db.execute("ALTER TABLE assignment ADD COLUMN due_date TEXT")

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def configure(self, timezone: str, reminder_minutes: list[int]) -> None:
        now = self._now()
        with self.transaction() as db:
            db.execute(
                """INSERT INTO account(id, timezone, created_at, updated_at)
                VALUES(1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                timezone=excluded.timezone, updated_at=excluded.updated_at""",
                (timezone, now, now),
            )
            for minutes in reminder_minutes:
                db.execute(
                    """INSERT OR IGNORE INTO reminder_rule(antecedence_minutes, enabled)
                    VALUES(?, 1)""",
                    (minutes,),
                )

    def upsert_course(self, course: Course) -> int:
        with self.transaction() as db:
            db.execute(
                """INSERT INTO course(google_course_id, name, active, updated_at) VALUES(?, ?, ?, ?)
                ON CONFLICT(google_course_id) DO UPDATE SET
                    name=excluded.name, active=excluded.active, updated_at=excluded.updated_at""",
                (course.google_course_id, course.name, int(course.active), self._now()),
            )
            row = db.execute(
                "SELECT id FROM course WHERE google_course_id=?", (course.google_course_id,)
            ).fetchone()
            return int(row["id"])

    def upsert_assignment(self, assignment: Assignment) -> int:
        with self.transaction() as db:
            course_row = db.execute(
                "SELECT id FROM course WHERE google_course_id=?", (assignment.course_id,)
            ).fetchone()
            if course_row is None:
                raise ValueError(f"curso inexistente: {assignment.course_id}")
            course_id = int(course_row["id"])
            old = db.execute(
                "SELECT id, due_utc FROM assignment WHERE course_id=? AND google_work_id=?",
                (course_id, assignment.google_work_id),
            ).fetchone()
            due = assignment.due_utc.astimezone(UTC).isoformat() if assignment.due_utc else None
            db.execute(
                """INSERT INTO assignment(
                    course_id, google_work_id, title, url, due_utc, due_date, has_due_time,
                    submission_state, deleted, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(course_id, google_work_id) DO UPDATE SET
                    title=excluded.title, url=excluded.url, due_utc=excluded.due_utc,
                    due_date=excluded.due_date,
                    has_due_time=excluded.has_due_time,
                    submission_state=excluded.submission_state, deleted=excluded.deleted,
                    updated_at=excluded.updated_at""",
                (
                    course_id,
                    assignment.google_work_id,
                    assignment.title,
                    assignment.url,
                    due,
                    assignment.due_date.isoformat() if assignment.due_date else None,
                    int(assignment.has_due_time),
                    assignment.submission_state.value,
                    int(assignment.deleted),
                    self._now(),
                ),
            )
            row = db.execute(
                "SELECT id FROM assignment WHERE course_id=? AND google_work_id=?",
                (course_id, assignment.google_work_id),
            ).fetchone()
            assignment_id = int(row["id"])
            if old is not None and old["due_utc"] != due:
                db.execute(
                    """UPDATE notification_event SET state=?
                    WHERE assignment_id=? AND state IN (?, ?, ?)""",
                    (
                        EventState.CANCELLED.value,
                        assignment_id,
                        EventState.PLANNED.value,
                        EventState.FAILED.value,
                        EventState.ATTEMPTED.value,
                    ),
                )
            if not assignment.reminder_eligible:
                db.execute(
                    "UPDATE notification_event SET state=? WHERE assignment_id=? AND state=?",
                    (EventState.CANCELLED.value, assignment_id, EventState.PLANNED.value),
                )
            return assignment_id

    def assignments(self, include_deleted: bool = False) -> list[tuple[int, str, Assignment]]:
        query = """SELECT a.*, c.google_course_id, c.name AS course_name
            FROM assignment a JOIN course c ON c.id=a.course_id"""
        if not include_deleted:
            query += " WHERE a.deleted=0 AND c.active=1"
        query += " ORDER BY a.due_utc IS NULL, a.due_utc, a.title"
        with self.transaction() as db:
            rows = db.execute(query).fetchall()
        result = []
        for row in rows:
            due = datetime.fromisoformat(row["due_utc"]) if row["due_utc"] else None
            result.append(
                (
                    int(row["id"]),
                    str(row["course_name"]),
                    Assignment(
                        course_id=str(row["google_course_id"]),
                        google_work_id=str(row["google_work_id"]),
                        title=str(row["title"]),
                        url=row["url"],
                        due_utc=due,
                        has_due_time=bool(row["has_due_time"]),
                        submission_state=SubmissionState(row["submission_state"]),
                        deleted=bool(row["deleted"]),
                        due_date=datetime.fromisoformat(row["due_date"]).date()
                        if row["due_date"]
                        else None,
                    ),
                )
            )
        return result

    def mark_missing_assignments(self, google_course_id: str, present_work_ids: set[str]) -> int:
        with self.transaction() as db:
            course = db.execute(
                "SELECT id FROM course WHERE google_course_id=?", (google_course_id,)
            ).fetchone()
            if course is None:
                return 0
            rows = db.execute(
                "SELECT id, google_work_id FROM assignment WHERE course_id=? AND deleted=0",
                (course["id"],),
            ).fetchall()
            missing = [
                int(row["id"]) for row in rows if row["google_work_id"] not in present_work_ids
            ]
            for assignment_id in missing:
                db.execute("UPDATE assignment SET deleted=1 WHERE id=?", (assignment_id,))
                db.execute(
                    """UPDATE notification_event SET state=?
                    WHERE assignment_id=? AND state IN (?, ?)""",
                    (
                        EventState.CANCELLED.value,
                        assignment_id,
                        EventState.PLANNED.value,
                        EventState.FAILED.value,
                    ),
                )
            return len(missing)

    def mark_missing_courses(self, present_course_ids: set[str]) -> int:
        with self.transaction() as db:
            rows = db.execute("SELECT id, google_course_id FROM course WHERE active=1").fetchall()
            missing = [
                int(row["id"]) for row in rows if row["google_course_id"] not in present_course_ids
            ]
            for course_id in missing:
                db.execute("UPDATE course SET active=0 WHERE id=?", (course_id,))
                db.execute(
                    """UPDATE notification_event SET state=?
                    WHERE assignment_id IN (
                        SELECT id FROM assignment WHERE course_id=?
                    ) AND state IN (?, ?)""",
                    (
                        EventState.CANCELLED.value,
                        course_id,
                        EventState.PLANNED.value,
                        EventState.FAILED.value,
                    ),
                )
            return len(missing)

    def create_event(
        self, assignment_id: int, milestone_minutes: int, due_utc: datetime, channel: str
    ) -> int | None:
        with self.transaction() as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO notification_event(
                    assignment_id, milestone_minutes, due_utc, channel, state, created_at
                ) VALUES(?, ?, ?, ?, ?, ?)""",
                (
                    assignment_id,
                    milestone_minutes,
                    due_utc.astimezone(UTC).isoformat(),
                    channel,
                    EventState.PLANNED.value,
                    self._now(),
                ),
            )
            if not cursor.rowcount:
                return None
            assert cursor.lastrowid is not None
            return int(cursor.lastrowid)

    def pending_events(self) -> list[NotificationEvent]:
        with self.transaction() as db:
            rows = db.execute(
                """SELECT e.*, a.title, a.url, c.name AS course_name
                FROM notification_event e
                JOIN assignment a ON a.id=e.assignment_id
                JOIN course c ON c.id=a.course_id
                WHERE e.state IN (?, ?) ORDER BY e.created_at""",
                (EventState.PLANNED.value, EventState.FAILED.value),
            ).fetchall()
        return [
            NotificationEvent(
                event_id=int(row["id"]),
                assignment_id=int(row["assignment_id"]),
                milestone_minutes=int(row["milestone_minutes"]),
                due_utc=datetime.fromisoformat(row["due_utc"]),
                channel=str(row["channel"]),
                state=EventState(row["state"]),
                title=str(row["title"]),
                course_name=str(row["course_name"]),
                url=row["url"],
            )
            for row in rows
        ]

    def update_event(
        self,
        event_id: int,
        state: EventState,
        provider_id: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.transaction() as db:
            db.execute(
                """UPDATE notification_event SET state=?, attempts=attempts+1,
                sent_at=?, provider_id=COALESCE(?, provider_id), last_error=? WHERE id=?""",
                (state.value, self._now(), provider_id, error, event_id),
            )

    def status_counts(self) -> dict[str, int]:
        with self.transaction() as db:
            rows = db.execute(
                "SELECT state, count(*) count FROM notification_event GROUP BY state"
            ).fetchall()
        return {str(row["state"]): int(row["count"]) for row in rows}

    def record_sync(self, result: str, error: str | None = None) -> None:
        now = self._now()
        with self.transaction() as db:
            db.execute(
                "INSERT INTO sync_run(started_at, finished_at, result, error) VALUES(?, ?, ?, ?)",
                (now, now, result, error),
            )

    def latest_sync(self) -> sqlite3.Row | None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM sync_run ORDER BY id DESC LIMIT 1").fetchone()
            return cast(sqlite3.Row | None, row)

    def save_consent(self, channel: str, remote_id: str, version: str) -> None:
        with self.transaction() as db:
            db.execute(
                """INSERT INTO channel_consent(channel, remote_id, consent_version, accepted_at)
                VALUES(?, ?, ?, ?) ON CONFLICT(channel) DO UPDATE SET
                remote_id=excluded.remote_id, consent_version=excluded.consent_version,
                accepted_at=excluded.accepted_at, revoked_at=NULL""",
                (channel, remote_id, version, self._now()),
            )

    def revoke_consent(self, channel: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE channel_consent SET revoked_at=? WHERE channel=?",
                (self._now(), channel),
            )

    def apply_retention(self, event_days: int = 180, sync_days: int = 30) -> None:
        event_cutoff = (datetime.now(UTC) - timedelta(days=event_days)).isoformat()
        sync_cutoff = (datetime.now(UTC) - timedelta(days=sync_days)).isoformat()
        with self.transaction() as db:
            db.execute(
                "DELETE FROM notification_event WHERE created_at < ? AND state IN (?, ?, ?)",
                (
                    event_cutoff,
                    EventState.CONFIRMED.value,
                    EventState.DELIVERED.value,
                    EventState.CANCELLED.value,
                ),
            )
            db.execute("DELETE FROM sync_run WHERE started_at < ?", (sync_cutoff,))
