from __future__ import annotations

import sys
import threading
import time
from types import TracebackType
from typing import TextIO


class ProgressIndicator:
    """Indicador indeterminado seguro para terminal e execução não interativa."""

    FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(
        self,
        message: str,
        *,
        stream: TextIO | None = None,
        interval: float = 0.1,
    ) -> None:
        self.message = message
        self.stream = stream or sys.stderr
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0
        self._interactive = bool(getattr(self.stream, "isatty", lambda: False)())

    def __enter__(self) -> ProgressIndicator:
        self._started = time.monotonic()
        if self._interactive:
            self._thread = threading.Thread(target=self._animate, daemon=True)
            self._thread.start()
        else:
            print(f"{self.message}...", file=self.stream, flush=True)
        return self

    def _animate(self) -> None:
        frame = 0
        while not self._stop.wait(self.interval):
            elapsed = time.monotonic() - self._started
            text = f"\r\033[2K{self.FRAMES[frame]} {self.message} ({elapsed:.1f}s)"
            print(text, end="", file=self.stream, flush=True)
            frame = (frame + 1) % len(self.FRAMES)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval * 2))
            elapsed = time.monotonic() - self._started
            symbol = "✓" if exc_type is None else "✗"
            print(
                f"\r\033[2K{symbol} {self.message} ({elapsed:.1f}s)",
                file=self.stream,
                flush=True,
            )
