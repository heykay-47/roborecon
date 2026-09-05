from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class ReadTiming:
    database_ms: float = 0.0

    def add_database_ms(self, duration_ms: float) -> None:
        self.database_ms += duration_ms


current_read_timing: ContextVar[ReadTiming | None] = ContextVar(
    "current_read_timing", default=None
)
