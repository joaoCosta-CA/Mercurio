import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mercurio.cli import main


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.env = {
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_STATE_HOME": str(root / "state"),
        }
        self.fixture = Path(__file__).parent / "fixtures/classroom.json"
        self.environment = patch.dict(os.environ, self.env)
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp.cleanup()

    def invoke(self, arguments):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_local_workflow_and_status(self) -> None:
        self.assertEqual(self.invoke(["setup", "--timezone", "UTC"])[0], 0)
        code, output, _ = self.invoke(["sync", "--fixture", str(self.fixture)])
        self.assertEqual(code, 0)
        self.assertIn("2 atividade", output)

        code, output, _ = self.invoke(["atividades", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload[0]["title"], "Lista de Laplace")
        self.assertEqual(payload[1]["due_date"], "2026-10-20")

        code, output, _ = self.invoke(["atividades"])
        self.assertEqual(code, 0)
        self.assertIn("horário indefinido", output)

        code, output, _ = self.invoke(["avisos", "--at", "2026-10-15T15:00:00+00:00"])
        self.assertEqual(code, 0)
        self.assertIn("Lembrete acadêmico", output)

        code, output, _ = self.invoke(["avisos", "--historico"])
        self.assertEqual(code, 0)
        self.assertIn("Lista de Laplace", output)
        self.assertIn("confirmado", output)

        code, output, _ = self.invoke(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Última sincronização", output)

    def test_auth_commands(self) -> None:
        with patch("mercurio.cli.has_credentials", return_value=False):
            self.assertIn("não autorizada", self.invoke(["auth", "status"])[1])
        with patch("mercurio.cli.login") as login:
            code, output, _ = self.invoke(["auth", "login", "--client-secrets", "/tmp/client.json"])
            self.assertEqual(code, 0)
            login.assert_called_once()
            self.assertIn("autorizada", output)
        with patch("mercurio.cli.logout") as logout:
            self.assertEqual(self.invoke(["auth", "logout"])[0], 0)
            logout.assert_called_once()

    def test_whatsapp_connect_disconnect(self) -> None:
        responses = [
            FakeResponse({"id": "enrollment", "development_code": "123456"}),
            FakeResponse({"recipient_id": "recipient", "device_token": "secret"}),
        ]
        fake_httpx = SimpleNamespace(
            post=lambda *args, **kwargs: responses.pop(0),
            delete=lambda *args, **kwargs: FakeResponse({}),
        )
        with patch.dict("sys.modules", {"httpx": fake_httpx}):
            code, output, _ = self.invoke(
                [
                    "canal",
                    "whatsapp",
                    "conectar",
                    "--base-url",
                    "https://gateway.example",
                    "--invite-code",
                    "invite",
                    "--phone",
                    "+5511999999999",
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("conectado", output)
            code, output, _ = self.invoke(["canal", "whatsapp", "desconectar"])
            self.assertEqual(code, 0)
            self.assertIn("revogado", output)

    def test_systemd_commands_delegate(self) -> None:
        with (
            patch("mercurio.cli._install_units") as install,
            patch("mercurio.cli._systemctl", return_value=0) as systemctl,
        ):
            self.assertEqual(self.invoke(["start"])[0], 0)
            install.assert_called_once()
            self.assertEqual(systemctl.call_count, 2)
            self.assertEqual(self.invoke(["stop"])[0], 0)

    def test_data_erase_requires_confirmation(self) -> None:
        self.invoke(["setup"])
        code, _, error = self.invoke(["dados", "apagar", "--confirmar", "não"])
        self.assertEqual(code, 1)
        self.assertIn("confirmação inválida", error)
        with patch("mercurio.cli.logout"):
            code, output, _ = self.invoke(["dados", "apagar", "--confirmar", "APAGAR"])
        self.assertEqual(code, 0)
        self.assertIn("removidos", output)

    def test_sync_lock_error_is_friendly(self) -> None:
        with patch("mercurio.cli.process_lock", side_effect=RuntimeError("ocupado")):
            code, _, error = self.invoke(["sync", "--fixture", str(self.fixture)])
        self.assertEqual(code, 1)
        self.assertIn("ocupado", error)

    def test_active_filter_hides_expired_and_delivered_assignments(self) -> None:
        self.invoke(["setup", "--timezone", "UTC"])
        self.invoke(["sync", "--fixture", str(self.fixture)])
        with patch("mercurio.cli.datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 17, tzinfo=UTC)
            code, output, _ = self.invoke(["atividades", "--ativas", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual([item["title"] for item in json.loads(output)], ["Lista de Laplace"])
