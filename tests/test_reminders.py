import unittest
from datetime import UTC, datetime, timedelta

from mercurio.domain.models import Assignment, SubmissionState
from mercurio.domain.reminders import choose_candidate, human_duration


class ReminderTests(unittest.TestCase):
    def assignment(
        self, due: datetime, state: SubmissionState = SubmissionState.CREATED
    ) -> Assignment:
        return Assignment("c", "w", "Teste", None, due, True, state)

    def test_exact_milestone(self) -> None:
        due = datetime(2026, 10, 20, 12, tzinfo=UTC)
        candidate = choose_candidate(
            self.assignment(due), due - timedelta(days=3), [10080, 4320, 1440, 120], 15
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.milestone_minutes, 4320)

    def test_resume_uses_most_recent_useful_milestone(self) -> None:
        due = datetime(2026, 10, 20, 12, tzinfo=UTC)
        candidate = choose_candidate(
            self.assignment(due), due - timedelta(minutes=30), [10080, 4320, 1440, 120], 15
        )
        self.assertEqual(candidate.milestone_minutes, 120)

    def test_completed_and_expired_are_ignored(self) -> None:
        due = datetime(2026, 10, 20, 12, tzinfo=UTC)
        now = due - timedelta(days=1)
        self.assertIsNone(
            choose_candidate(self.assignment(due, SubmissionState.TURNED_IN), now, [1440], 15)
        )
        self.assertIsNone(choose_candidate(self.assignment(due), due, [1440], 15))

    def test_naive_now_rejected(self) -> None:
        due = datetime(2026, 10, 20, 12, tzinfo=UTC)
        with self.assertRaises(ValueError):
            choose_candidate(self.assignment(due), datetime(2026, 10, 19), [1440], 15)

    def test_human_duration(self) -> None:
        self.assertEqual(human_duration(1440), "1 dia")
        self.assertEqual(human_duration(120), "2 horas")
