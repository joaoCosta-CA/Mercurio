import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mercurio.config import Settings
from mercurio.domain.models import Assignment, Course, EventState, SubmissionState
from mercurio.notifications.base import DeliveryResult
from mercurio.services import deliver_pending, evaluate_reminders, synchronize
from mercurio.storage.sqlite import Database


class FakeSource:
    def __init__(self, due: datetime) -> None:
        self.due = due

    def fetch(self):
        yield (
            Course("c1", "Curso"),
            [
                Assignment(
                    "c1",
                    "w1",
                    "Trabalho",
                    "https://example",
                    self.due,
                    True,
                    SubmissionState.CREATED,
                )
            ],
        )


class EmptySource:
    def fetch(self):
        yield Course("c1", "Curso"), []


class NoCourseSource:
    def fetch(self):
        return iter(())


class FakeNotifier:
    def __init__(self, accepted=True) -> None:
        self.accepted = accepted

    def send(self, event):
        return DeliveryResult(
            self.accepted,
            "provider-1" if self.accepted else None,
            None if self.accepted else "offline",
        )


class StorageServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.settings = Settings(timezone="UTC")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_sync_evaluate_deliver_and_idempotency(self) -> None:
        now = datetime(2026, 10, 14, 12, tzinfo=UTC)
        due = now + timedelta(days=3)
        self.assertEqual(synchronize(self.db, FakeSource(due)), (1, 1))
        self.assertEqual(evaluate_reminders(self.db, self.settings, now), 1)
        self.assertEqual(evaluate_reminders(self.db, self.settings, now), 0)
        self.assertEqual(deliver_pending(self.db, FakeNotifier()), (1, 0))
        self.assertEqual(self.db.status_counts(), {EventState.CONFIRMED.value: 1})

    def test_due_change_cancels_old_event(self) -> None:
        now = datetime(2026, 10, 14, 12, tzinfo=UTC)
        synchronize(self.db, FakeSource(now + timedelta(days=3)))
        evaluate_reminders(self.db, self.settings, now)
        synchronize(self.db, FakeSource(now + timedelta(days=4)))
        self.assertEqual(self.db.status_counts(), {EventState.CANCELLED.value: 1})

    def test_completed_update_cancels_planned(self) -> None:
        now = datetime(2026, 10, 14, 12, tzinfo=UTC)
        due = now + timedelta(days=1)
        synchronize(self.db, FakeSource(due))
        evaluate_reminders(self.db, self.settings, now)
        self.db.upsert_assignment(
            Assignment("c1", "w1", "Trabalho", None, due, True, SubmissionState.TURNED_IN)
        )
        self.assertEqual(self.db.status_counts(), {EventState.CANCELLED.value: 1})

    def test_failed_delivery_is_retryable(self) -> None:
        now = datetime(2026, 10, 14, 12, tzinfo=UTC)
        synchronize(self.db, FakeSource(now + timedelta(hours=2)))
        evaluate_reminders(self.db, self.settings, now)
        self.assertEqual(deliver_pending(self.db, FakeNotifier(False)), (0, 1))
        self.assertEqual(deliver_pending(self.db, FakeNotifier(True)), (1, 0))

    def test_removed_assignment_is_hidden_and_event_cancelled(self) -> None:
        now = datetime(2026, 10, 14, 12, tzinfo=UTC)
        synchronize(self.db, FakeSource(now + timedelta(days=1)))
        evaluate_reminders(self.db, self.settings, now)
        synchronize(self.db, EmptySource())
        self.assertEqual(self.db.assignments(), [])
        self.assertEqual(self.db.status_counts(), {EventState.CANCELLED.value: 1})

    def test_removed_course_is_hidden_and_event_cancelled(self) -> None:
        now = datetime(2026, 10, 14, 12, tzinfo=UTC)
        synchronize(self.db, FakeSource(now + timedelta(days=1)))
        evaluate_reminders(self.db, self.settings, now)
        synchronize(self.db, NoCourseSource())
        self.assertEqual(self.db.assignments(), [])
        self.assertEqual(self.db.status_counts(), {EventState.CANCELLED.value: 1})
