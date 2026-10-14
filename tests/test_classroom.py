import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from mercurio.domain.models import SubmissionState
from mercurio.integrations.classroom import FixtureClassroom, GoogleClassroom, normalize_assignment


class Request:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    def execute(self):
        value = self.payloads.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class SubmissionResource:
    def list(self, **kwargs):
        if kwargs["pageToken"] is None:
            return Request([{"studentSubmissions": [], "nextPageToken": "s2"}])
        return Request([{"studentSubmissions": [{"state": "CREATED"}]}])


class WorkResource:
    def list(self, **kwargs):
        if kwargs["pageToken"] is None:
            return Request(
                [
                    {
                        "courseWork": [{"id": "w1", "title": "Trabalho"}],
                        "nextPageToken": "w2",
                    }
                ]
            )
        return Request([{"courseWork": []}])

    def studentSubmissions(self):
        return SubmissionResource()


class CourseResource:
    def list(self, **kwargs):
        if kwargs["pageToken"] is None:
            return Request([{"courses": [{"id": "c1", "name": "Curso"}], "nextPageToken": "c2"}])
        return Request([{"courses": []}])

    def courseWork(self):
        return WorkResource()


class Service:
    def courses(self):
        return CourseResource()


class ClassroomTests(unittest.TestCase):
    def test_fixture_normalizes_due_time(self) -> None:
        source = FixtureClassroom(Path(__file__).parent / "fixtures/classroom.json")
        course, assignments = next(source.fetch())
        self.assertEqual(course.name, "Equações Diferenciais")
        self.assertEqual(assignments[0].due_utc, datetime(2026, 10, 18, 15, tzinfo=UTC))
        self.assertTrue(assignments[0].has_due_time)
        self.assertIsNone(assignments[1].due_utc)
        self.assertEqual(assignments[1].due_date.isoformat(), "2026-10-20")
        self.assertFalse(assignments[1].reminder_eligible)

    def test_unknown_submission_state_is_safe(self) -> None:
        assignment = normalize_assignment("c", {"id": "w", "title": "T"}, {"state": "FUTURE_STATE"})
        self.assertEqual(assignment.submission_state, SubmissionState.UNKNOWN)

    def test_invalid_due_date_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_assignment(
                "c",
                {"id": "w", "dueDate": {"year": 2026}, "dueTime": {"hours": 1}},
            )

    def test_google_fetch_paginates_all_resources(self) -> None:
        classroom = GoogleClassroom.__new__(GoogleClassroom)
        classroom.service = Service()
        rows = list(classroom.fetch())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1][0].submission_state, SubmissionState.CREATED)

    def test_google_request_retries_transient_failure(self) -> None:
        request = Request([OSError("offline"), {"ok": True}])
        with patch("mercurio.integrations.classroom.time.sleep") as sleep:
            self.assertEqual(GoogleClassroom._execute(request), {"ok": True})
        sleep.assert_called_once_with(1)
