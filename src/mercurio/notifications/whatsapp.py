from __future__ import annotations

from typing import Any

from mercurio.domain.models import NotificationEvent

from .base import DeliveryResult


class WhatsAppNotifier:
    def __init__(self, base_url: str, recipient_id: str, device_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.recipient_id = recipient_id
        self.device_token = device_token

    def send(self, event: NotificationEvent) -> DeliveryResult:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("instale o extra whatsapp-client") from exc
        payload: dict[str, Any] = {
            "recipient_id": self.recipient_id,
            "template": "lembrete_academico",
            "variables": {
                "course": event.course_name,
                "assignment": event.title,
                "due_at": event.due_utc.isoformat(),
                "url": event.url or "",
            },
        }
        try:
            response = httpx.post(
                f"{self.base_url}/v1/notifications",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.device_token}",
                    "Idempotency-Key": event.idempotency_key,
                },
                timeout=15,
            )
            response.raise_for_status()
            body = response.json()
            return DeliveryResult(True, body.get("provider_id") or body.get("id"))
        except Exception as exc:
            return DeliveryResult(False, error=str(exc)[:300])
