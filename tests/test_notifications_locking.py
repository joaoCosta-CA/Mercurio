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
