"""Optional, synchronous progress observations; no task storage or dependencies."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from langparse.logging import get_logger

logger = get_logger(__name__)
ProgressState = Literal["running", "completed", "failed", "skipped"]


@dataclass(frozen=True)
class ProgressEvent:
    """Percent is 0–100 within phase, never an estimate of remaining time.

    A file's lifecycle ends only at phase='file', state='completed'/'failed'.
    Completion does not imply that the result's quality diagnostics are successful.
    Unknown amounts remain None. An empty source identifies the batch itself.
    """

    source: str
    phase: str
    state: ProgressState = "running"
    completed_units: int | None = None
    total_units: int | None = None
    unit: str | None = None
    percent: float | None = None
    message: str = ""


ProgressCallback = Callable[[ProgressEvent], None]


class ProgressReporter:
    """Internal adapter keeping observer failures out of parsing and fallback paths."""

    def __init__(self, source: str | Path, callback: ProgressCallback | None = None):
        self.source = str(source)
        self.callback = callback

    def emit(
        self,
        phase: str,
        *,
        state: ProgressState = "running",
        completed_units: int | None = None,
        total_units: int | None = None,
        unit: str | None = None,
        percent: float | None = None,
        message: str = "",
    ) -> None:
        if self.callback is None:
            return
        if percent is None and completed_units is not None and total_units:
            percent = 100.0 * completed_units / total_units
        event = ProgressEvent(
            self.source, phase, state, completed_units, total_units, unit, percent, message
        )
        try:
            self.callback(event)
        except Exception as exc:
            # Do not include observer exceptions' text: it may contain credentials.
            logger.warning("Progress callback failed (%s)", type(exc).__name__)

    @contextmanager
    def operation(self, phase: str) -> Iterator[None]:
        self.emit(phase)
        try:
            yield
        except Exception as exc:
            self.emit(phase, state="failed", message=type(exc).__name__)
            raise
        else:
            self.emit(phase, state="completed")
