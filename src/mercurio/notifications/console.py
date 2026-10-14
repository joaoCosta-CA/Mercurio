from __future__ import annotations

from zoneinfo import ZoneInfo

from mercurio.domain.models import NotificationEvent
from mercurio.domain.reminders import human_duration

from .base import DeliveryResult


class ConsoleNotifier:
    def __init__(self, timezone: str = "America/Sao_Paulo") -> None:
        self.timezone = ZoneInfo(timezone)

    def send(self, event: NotificationEvent) -> DeliveryResult:
        due = event.due_utc.astimezone(self.timezone).strftime("%d/%m/%Y às %H:%M")
        print("Mercúrio · Lembrete acadêmico")
        print(f"Disciplina: {event.course_name}")
        print(f"Atividade: {event.title}")
        print(f"Prazo: {due}")
        print(f"Marco: {human_duration(event.milestone_minutes)}")
        if event.url:
            print(f"Acesse a atividade: {event.url}")
        return DeliveryResult(True, f"console:{event.event_id}")
