import time
import unittest
from io import StringIO

from mercurio.progress import ProgressIndicator


class InteractiveStream(StringIO):
    def isatty(self) -> bool:
        return True


class ProgressIndicatorTests(unittest.TestCase):
    def test_non_interactive_output_is_static(self) -> None:
        stream = StringIO()
        with ProgressIndicator("Sincronizando", stream=stream):
            pass
        self.assertEqual(stream.getvalue(), "Sincronizando...\n")

    def test_interactive_output_animates_and_finishes(self) -> None:
        stream = InteractiveStream()
        with ProgressIndicator("Sincronizando", stream=stream, interval=0.001):
            time.sleep(0.005)
        output = stream.getvalue()
        self.assertIn("Sincronizando", output)
        self.assertIn("✓", output)

    def test_interactive_failure_has_error_marker(self) -> None:
        stream = InteractiveStream()
        with (
            self.assertRaisesRegex(RuntimeError, "falha"),
            ProgressIndicator("Sincronizando", stream=stream, interval=0.001),
        ):
            raise RuntimeError("falha")
        self.assertIn("✗", stream.getvalue())
