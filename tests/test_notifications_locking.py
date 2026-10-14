import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mercurio.domain.models import EventState, NotificationEvent
from mercurio.locking import process_lock
from mercurio.notifications.console import ConsoleNotifier
from mercurio.notifications.desktop import DesktopNotifier
from mercurio.notifications.whatsapp import WhatsAppNotifier


def event():
    return NotificationEvent(
        1,
        2,
        120,
        datetime(2026, 10, 18, 15, tzinfo=UTC),
        "console",
        EventState.PLANNED,
        "Lista",
        "Matemática",
        "https://example",
    )


class NotificationAndLockTests(unittest.TestCase):
    def test_console_message(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            result = ConsoleNotifier("UTC").send(event())
        self.assertTrue(result.accepted)
        self.assertIn("Matemática", output.getvalue())

    def test_desktop_message_uses_notification_bus(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with (
            patch("mercurio.notifications.desktop.os.environ.copy", return_value={}),
            patch("mercurio.notifications.desktop.os.getuid", return_value=1000),
            patch("mercurio.notifications.desktop.subprocess.run", return_value=completed) as run,
        ):
            result = DesktopNotifier("UTC").send(event())
        self.assertTrue(result.accepted)
        self.assertEqual(result.provider_id, "desktop:1")
        command = run.call_args.args[0]
        self.assertIn("--app-name=Mercúrio", command)
        self.assertIn("Matemática", command[-1])
        self.assertEqual(
            run.call_args.kwargs["env"]["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/1000/bus"
        )

    def test_desktop_failure_is_reported(self) -> None:
        with patch(
            "mercurio.notifications.desktop.subprocess.run",
            return_value=SimpleNamespace(returncode=1, stdout="", stderr="D-Bus indisponível"),
        ):
            result = DesktopNotifier("UTC").send(event())
        self.assertFalse(result.accepted)
        self.assertIn("D-Bus indisponível", result.error)

        with patch("mercurio.notifications.desktop.subprocess.run", side_effect=FileNotFoundError):
            result = DesktopNotifier("UTC").send(event())
        self.assertFalse(result.accepted)
        self.assertIn("não está instalado", result.error)

    def test_whatsapp_success_and_failure(self) -> None:
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"provider_id": "provider"},
        )
        fake_httpx = SimpleNamespace(post=lambda *args, **kwargs: response)
        with patch.dict("sys.modules", {"httpx": fake_httpx}):
            result = WhatsAppNotifier("https://gateway", "recipient", "token").send(event())
            self.assertTrue(result.accepted)
            self.assertEqual(result.provider_id, "provider")

        fake_httpx = SimpleNamespace(
            post=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline"))
        )
        with patch.dict("sys.modules", {"httpx": fake_httpx}):
            result = WhatsAppNotifier("https://gateway", "recipient", "token").send(event())
            self.assertFalse(result.accepted)
            self.assertIn("offline", result.error)

    def test_process_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state" / "sync.lock"
            with process_lock(path):
                self.assertTrue(path.exists())
                with self.assertRaises(RuntimeError), process_lock(path):
                    pass
