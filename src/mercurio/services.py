from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mercurio.config import Settings
from mercurio.domain.models import EventState
from mercurio.domain.reminders import choose_candidate
from mercurio.notifications.base import Notifier
from mercurio.storage.sqlite import Database


def synchronize(db: Database, source: Any) -> tuple[int, int]:
    courses = assignments = 0
    present_courses: set[str] = set()
    try:
        for course, items in source.fetch():
            db.upsert_course(course)
            present_courses.add(course.google_course_id)
            courses += 1
            present_ids: set[str] = set()
            for assignment in items:
                db.upsert_assignment(assignment)
                present_ids.add(assignment.google_work_id)
                assignments += 1
            db.mark_missing_assignments(course.google_course_id, present_ids)
        db.mark_missing_courses(present_courses)
        db.record_sync("sucesso")
        return courses, assignments
    except Exception as exc:
        db.record_sync("falha", str(exc)[:300])
        raise


def evaluate_reminders(
    db: Database,
    settings: Settings,
    now: datetime | None = None,
    channel: str = "console",
) -> int:
    now = now or datetime.now(UTC)
    created = 0
    for assignment_id, _course_name, assignment in db.assignments():
        candidate = choose_candidate(
            assignment,
            now,
            settings.reminder_minutes,
            settings.sync_interval_minutes,
        )
        if candidate and assignment.due_utc:
            event_id = db.create_event(
                assignment_id, candidate.milestone_minutes, assignment.due_utc, channel
            )
            created += int(event_id is not None)
    return created


def deliver_pending(
    db: Database, notifier: Notifier, channel: str | None = None
) -> tuple[int, int]:
    accepted = failed = 0
    for event in db.pending_events():
        if channel is not None and event.channel != channel:
            continue
        result = notifier.send(event)
        if result.accepted:
            db.update_event(event.event_id, EventState.CONFIRMED, result.provider_id)
            accepted += 1
        else:
            db.update_event(event.event_id, EventState.FAILED, error=result.error)
            failed += 1
    return accepted, failed
