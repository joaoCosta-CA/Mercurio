import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mercurio.config import Paths
from mercurio.integrations.google_auth import (
    SCOPES,
    STUDENT_SUBMISSIONS_SCOPE,
    _validate_granted_scopes,
    has_credentials,
    load_credentials,
    logout,
)


class GoogleAuthTests(unittest.TestCase):
    def paths(self, root: Path) -> Paths:
        return Paths(root / "config", root / "data", root / "state")

    def test_file_credential_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            paths.ensure()
            paths.credential_file.write_text("{}", encoding="utf-8")
            with patch.dict("sys.modules", {"keyring": None}):
                self.assertTrue(has_credentials(paths))
                logout(paths)
                self.assertFalse(paths.credential_file.exists())
                self.assertFalse(has_credentials(paths))

    def test_load_without_credentials_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            with (
                patch.dict("sys.modules", {"keyring": None}),
                self.assertRaisesRegex(RuntimeError, "auth login"),
            ):
                load_credentials(paths)

    def test_known_google_scope_substitution_is_accepted(self) -> None:
        _validate_granted_scopes({SCOPES[0], STUDENT_SUBMISSIONS_SCOPE})

    def test_unexpected_or_incomplete_scopes_are_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "inesperadas"):
            _validate_granted_scopes({SCOPES[0], "https://example.invalid/write"})
        with self.assertRaisesRegex(RuntimeError, "não concedeu"):
            _validate_granted_scopes({SCOPES[0]})
