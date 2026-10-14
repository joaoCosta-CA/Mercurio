import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mercurio.config import Paths, Settings


class ConfigTests(unittest.TestCase):
    def test_xdg_paths_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
            }
            with patch.dict(os.environ, env):
                paths = Paths()
                settings = Settings(timezone="UTC", reminder_minutes=[120, 120, 1440])
                settings.save(paths)
                loaded = Settings.load(paths)
                self.assertEqual(loaded.reminder_minutes, [1440, 120])
                self.assertEqual(paths.config_file.stat().st_mode & 0o777, 0o600)

    def test_invalid_interval(self) -> None:
        with self.assertRaises(ValueError):
            Settings(sync_interval_minutes=0).validate()
