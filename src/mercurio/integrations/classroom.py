from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from datetime import date as date_type
from pathlib import Path
from typing import Any

from mercurio.domain.models import Assignment, Course, SubmissionState


def parse_due(work: dict[str, Any]) -> tuple[datetime | None, bool]:
    date = work.get("dueDate")
    time = work.get("dueTime")
    if not date:
        return None, False
    if not time:
        return None, False
    try:
        return (
            datetime(
                int(date["year"]),
                int(date["month"]),
                int(date["day"]),
                int(time.get("hours", 0)),
                int(time.get("minutes", 0)),
                int(time.get("seconds", 0)),
                tzinfo=UTC,
            ),
            True,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"prazo inválido para atividade {work.get('id', '<sem id>')}") from exc


def normalize_assignment(
    course_id: str, work: dict[str, Any], submission: dict[str, Any] | None = None
) -> Assignment:
    due, has_time = parse_due(work)
    raw_date = work.get("dueDate")
    due_date = None
    if raw_date:
        try:
            due_date = date_type(
                int(raw_date["year"]), int(raw_date["month"]), int(raw_date["day"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"data inválida para atividade {work.get('id', '<sem id>')}") from exc
    state_value = (submission or {}).get("state", "UNKNOWN")
    try:
        state = SubmissionState(state_value)
    except ValueError:
        state = SubmissionState.UNKNOWN
    return Assignment(
        course_id=course_id,
        google_work_id=str(work["id"]),
        title=str(work.get("title") or "Atividade sem título"),
        url=work.get("alternateLink"),
        due_utc=due,
        has_due_time=has_time,
        submission_state=state,
        due_date=due_date,
    )


class FixtureClassroom:
    def __init__(self, path: Path | str) -> None:
        self.payload = json.loads(Path(path).read_text(encoding="utf-8"))

    def fetch(self) -> Iterator[tuple[Course, list[Assignment]]]:
        submissions = {
            (str(s["courseId"]), str(s["courseWorkId"])): s
            for s in self.payload.get("submissions", [])
        }
        works_by_course: dict[str, list[Assignment]] = {}
        for work in self.payload.get("courseWork", []):
            course_id = str(work["courseId"])
            works_by_course.setdefault(course_id, []).append(
                normalize_assignment(course_id, work, submissions.get((course_id, str(work["id"]))))
            )
        for raw in self.payload.get("courses", []):
            course = Course(
                google_course_id=str(raw["id"]),
                name=str(raw.get("name") or "Curso sem nome"),
                active=raw.get("courseState", "ACTIVE") == "ACTIVE",
            )
            yield course, works_by_course.get(course.google_course_id, [])


class GoogleClassroom:
    def __init__(self, credentials: Any) -> None:
        try:
            from googleapiclient.discovery import build  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("instale o extra google: pip install -e '.[google]'") from exc
        self.service = build("classroom", "v1", credentials=credentials, cache_discovery=False)

    @staticmethod
    def _execute(request: Any) -> dict[str, Any]:
        for attempt in range(3):
            try:
                return dict(request.execute())
            except Exception as exc:
                status = getattr(getattr(exc, "resp", None), "status", None)
                retryable = status in {429, 500, 502, 503, 504} or status is None
                if attempt == 2 or not retryable:
                    raise
                time.sleep(2**attempt)
        raise RuntimeError("requisição Google não concluída")

    def fetch(self) -> Iterator[tuple[Course, list[Assignment]]]:
        # A paginação é feita explicitamente porque o cliente gerado varia entre versões.
        page_token = None
        courses: list[dict[str, Any]] = []
        while True:
            response = self._execute(
                self.service.courses().list(courseStates=["ACTIVE"], pageToken=page_token)
            )
            courses.extend(response.get("courses", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        for raw_course in courses:
            course_id = str(raw_course["id"])
            work_token = None
            works: list[dict[str, Any]] = []
            while True:
                response = self._execute(
                    self.service.courses()
                    .courseWork()
                    .list(courseId=course_id, pageToken=work_token)
                )
                works.extend(response.get("courseWork", []))
                work_token = response.get("nextPageToken")
                if not work_token:
                    break
            assignments = []
            for work in works:
                submissions: list[dict[str, Any]] = []
                submission_token = None
                while True:
                    sub_response = self._execute(
                        self.service.courses()
                        .courseWork()
                        .studentSubmissions()
                        .list(
                            courseId=course_id,
                            courseWorkId=str(work["id"]),
                            userId="me",
                            pageToken=submission_token,
                        )
                    )
                    submissions.extend(sub_response.get("studentSubmissions", []))
                    submission_token = sub_response.get("nextPageToken")
                    if not submission_token:
                        break
                assignments.append(
                    normalize_assignment(course_id, work, submissions[0] if submissions else None)
                )
            yield Course(course_id, str(raw_course.get("name", "Curso sem nome"))), assignments
