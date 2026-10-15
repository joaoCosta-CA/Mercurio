import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mercurio.config import Paths, Settings
from mercurio.domain.models import Assignment, Course, EventState, SubmissionState
from mercurio.storage.sqlite import Database
from mercurio.tui import MercurioApp


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

    async def _filters_activity_and_renders_history(self) -> None:
        app = MercurioApp(self.paths, self.settings, self.database)
        async with app.run_test() as pilot:
            await pilot.pause()
            activity_table = app.query_one("#activity-table")
            history_table = app.query_one("#history-table")
            self.assertEqual(activity_table.row_count, 1)
            self.assertEqual(history_table.row_count, 1)

            search = app.query_one("#search")
            search.value = "inexistente"
            await pilot.pause()
            self.assertEqual(activity_table.row_count, 0)
