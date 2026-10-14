from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Assignment


@dataclass(frozen=True, slots=True)
class ReminderCandidate:
    milestone_minutes: int
    scheduled_for: datetime


def choose_candidate(
    assignment: Assignment,
    now: datetime,
    milestones: Iterable[int],
    window_minutes: int,
) -> ReminderCandidate | None:
    """Retorna somente o marco útil mais recente, evitando enxurrada após pausa."""
    if now.tzinfo is None:
        raise ValueError("now deve ter fuso horário")
    if not assignment.reminder_eligible or assignment.due_utc is None:
        return None
    if now >= assignment.due_utc:
        return None

    eligible: list[ReminderCandidate] = []
    grace = timedelta(minutes=window_minutes)
    for minutes in sorted(set(milestones), reverse=True):
        scheduled = assignment.due_utc - timedelta(minutes=minutes)
        if scheduled <= now <= scheduled + grace or scheduled < now and now < assignment.due_utc:
            eligible.append(ReminderCandidate(minutes, scheduled))
    if not eligible:
        return None
    # O menor marco já atravessado é o aviso mais urgente e útil.
    return min(eligible, key=lambda item: item.milestone_minutes)


def human_duration(minutes: int) -> str:
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days} dia" if days == 1 else f"{days} dias"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hora" if hours == 1 else f"{hours} horas"
    return f"{minutes} minutos"
