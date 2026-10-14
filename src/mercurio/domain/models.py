from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class SubmissionState(StrEnum):
    NEW = "NEW"
    CREATED = "CREATED"
    TURNED_IN = "TURNED_IN"
    RETURNED = "RETURNED"
    RECLAIMED_BY_STUDENT = "RECLAIMED_BY_STUDENT"
    UNKNOWN = "UNKNOWN"

    @property
    def completed(self) -> bool:
        return self in {self.TURNED_IN, self.RETURNED}


class EventState(StrEnum):
    PLANNED = "planejado"
    ATTEMPTED = "tentado"
    CONFIRMED = "confirmado"
    DELIVERED = "entregue"
    FAILED = "falhou"
    CANCELLED = "cancelado"


@dataclass(frozen=True, slots=True)
class Course:
    google_course_id: str
    name: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class Assignment:
    course_id: str
    google_work_id: str
    title: str
    url: str | None
    due_utc: datetime | None
    has_due_time: bool
    submission_state: SubmissionState = SubmissionState.UNKNOWN
    deleted: bool = False
    due_date: date | None = None

    def __post_init__(self) -> None:
        if self.due_utc is not None and self.due_utc.tzinfo is None:
            raise ValueError("due_utc deve ter fuso horário")

    @property
    def reminder_eligible(self) -> bool:
        return (
            self.due_utc is not None
            and self.has_due_time
            and not self.submission_state.completed
            and not self.deleted
        )


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    event_id: int
    assignment_id: int
    milestone_minutes: int
    due_utc: datetime
    channel: str
    state: EventState
    title: str
    course_name: str
    url: str | None

    @property
    def idempotency_key(self) -> str:
        return (
            f"{self.assignment_id}:{self.milestone_minutes}:"
            f"{self.due_utc.isoformat()}:{self.channel}"
        )
