from __future__ import annotations

import os
import subprocess
from zoneinfo import ZoneInfo

from mercurio.domain.models import NotificationEvent
from mercurio.domain.reminders import human_duration

from .base import DeliveryResult


class DesktopNotifier:
    """Envia lembretes pelo servidor de notificações da sessão Linux."""

    def __init__(
        self, timezone: str = "America/Sao_Paulo", executable: str = "notify-send"
    ) -> None:
        self.timezone = ZoneInfo(timezone)
        self.executable = executable

    def send(self, event: NotificationEvent) -> DeliveryResult:
        due = event.due_utc.astimezone(self.timezone).strftime("%d/%m/%Y às %H:%M")
        body = "\n".join(
            (
                f"Disciplina: {event.course_name}",
                f"Atividade: {event.title}",
                f"Prazo: {due}",
                f"Marco: {human_duration(event.milestone_minutes)}",
            )
        )
        command = [
            self.executable,
            "--app-name=Mercúrio",
            "--urgency=normal",
            "--expire-time=10000",
            "--icon=appointment-soon",
            "Mercúrio · Lembrete acadêmico",
            body,
        ]
        environment = os.environ.copy()
        if not environment.get("DBUS_SESSION_BUS_ADDRESS"):
            runtime_dir = environment.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
            environment["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_dir}/bus"
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                env=environment,
            )
        except FileNotFoundError:
            return DeliveryResult(False, error="notify-send não está instalado")
        except subprocess.TimeoutExpired:
            return DeliveryResult(False, error="notify-send excedeu o tempo limite")
        except OSError as exc:
            return DeliveryResult(False, error=f"falha ao executar notify-send: {exc}")
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"código {result.returncode}"
            return DeliveryResult(False, error=f"notify-send falhou: {detail[:300]}")
        return DeliveryResult(True, f"desktop:{event.event_id}")
