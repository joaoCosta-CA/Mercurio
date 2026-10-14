from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mercurio.domain.models import NotificationEvent


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    accepted: bool
    provider_id: str | None = None
    error: str | None = None


class Notifier(Protocol):
    def send(self, event: NotificationEvent) -> DeliveryResult: ...
