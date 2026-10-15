import asyncio
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from mercurio.config import Paths, Settings
from mercurio.domain.models import Assignment, Course, EventState, SubmissionState
from mercurio.storage.sqlite import Database
from mercurio.tui import MercurioApp, find_client_secrets


class TuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = Paths(root / "config", root / "data", root / "state")
        self.paths.ensure()
        self.settings = Settings(timezone="UTC")
        self.database = Database(self.paths.database_file)
        self.database.upsert_course(Course("course", "Programação"))
        assignment_id = self.database.upsert_assignment(
            Assignment(
                "course",
                "work",
                "Projeto final",
                "https://example.test/activity",
                datetime.now(UTC) + timedelta(days=2),
                True,
                SubmissionState.CREATED,
            )
        )
        event_id = self.database.create_event(
            assignment_id,
            1440,
            datetime.now(UTC) + timedelta(days=2),
            "desktop",
        )
        assert event_id is not None
        self.database.update_event(event_id, EventState.CONFIRMED)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_filters_activity_and_renders_history(self) -> None:
        asyncio.run(self._filters_activity_and_renders_history())

    def test_long_table_values_are_truncated(self) -> None:
        self.assertEqual(
            MercurioApp._truncate("Arquitetura de Computadores"), "Arquitetura de Co..."
        )
        self.assertEqual(MercurioApp._truncate("Estado"), "Estado")

    def test_client_secret_lookup_prefers_environment_and_has_clear_errors(self) -> None:
        root = Path(self.temp.name) / "project"
        docs = root / "docs"
        docs.mkdir(parents=True)
        secret = docs / "client_secret_test.json"
        secret.touch()
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(find_client_secrets(root), secret)

        configured = Path(self.temp.name) / "custom-client.json"
        configured.touch()
        with patch.dict(os.environ, {"MERCURIO_CLIENT_SECRETS": str(configured)}, clear=True):
            self.assertEqual(find_client_secrets(root), configured)

        with (
            patch.dict(os.environ, {"MERCURIO_CLIENT_SECRETS": "inexistente"}, clear=True),
            self.assertRaisesRegex(RuntimeError, "não aponta"),
        ):
            find_client_secrets(root)

        empty_root = Path(self.temp.name) / "empty-project"
        (empty_root / "docs").mkdir(parents=True)
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(RuntimeError, "não encontrado"),
        ):
            find_client_secrets(empty_root)

        (empty_root / "docs" / "client_secret_first.json").touch()
        (empty_root / "docs" / "client_secret_second.json").touch()
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(RuntimeError, "mais de um"),
        ):
            find_client_secrets(empty_root)

    async def _filters_activity_and_renders_history(self) -> None:
        app = MercurioApp(self.paths, self.settings, self.database)
        async with app.run_test() as pilot:
            await pilot.pause()
            activity_table = app.query_one("#activity-table")
            history_table = app.query_one("#history-table")
            self.assertEqual(activity_table.row_count, 1)
            self.assertEqual(history_table.row_count, 1)
            self.assertEqual(activity_table.get_row_at(0)[3], "NÃO ENTREGUE")

            search = app.query_one("#search")
            search.value = "inexistente"
            await pilot.pause()
            self.assertEqual(activity_table.row_count, 0)
