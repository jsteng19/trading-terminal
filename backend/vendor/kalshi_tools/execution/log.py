"""
Structured logging for the execution engine.

Writes JSONL events to file and human-readable summaries to console.
"""

import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class LogEvent:
    """A structured log event."""

    event: str  # e.g. ORDER_PLACED, ORDER_FILLED, BOOK_UPDATE
    ticker: str = ""
    data: dict[str, Any] | None = None
    ts: str = ""

    def __post_init__(self):
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat()


class _JsonlHandler(logging.Handler):
    """Writes structured log events as JSONL lines."""

    def __init__(self, path: Path):
        super().__init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a")

    def emit(self, record: logging.LogRecord):
        if hasattr(record, "log_event"):
            line = json.dumps(asdict(record.log_event), default=str)  # type: ignore[arg-type]
        else:
            line = json.dumps(
                {"event": "LOG", "msg": record.getMessage(), "level": record.levelname}
            )
        self._file.write(line + "\n")
        self._file.flush()

    def close(self):
        self._file.close()
        super().close()


class _ConsoleFormatter(logging.Formatter):
    """Formats log events as readable one-liners for the terminal."""

    def format(self, record: logging.LogRecord) -> str:
        if hasattr(record, "log_event"):
            ev: LogEvent = record.log_event  # type: ignore[assignment]
            ts_short = ev.ts[11:19] if len(ev.ts) > 19 else ev.ts
            parts = [f"[{ts_short}]", ev.event]
            if ev.ticker:
                parts.append(ev.ticker)
            if ev.data:
                detail = " ".join(f"{k}={v}" for k, v in ev.data.items())
                parts.append(detail)
            return " ".join(parts)
        return super().format(record)


def setup_logger(log_dir: str = "logs", mode: str = "dry_run") -> logging.Logger:
    """Configure structured logging to JSONL file + console.

    Args:
        log_dir: Directory for log files.
        mode: Engine mode (used in filename).

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger("kalshi_engine")
    logger.setLevel(logging.DEBUG)
    # Avoid duplicate handlers on repeated calls
    logger.handlers.clear()

    # JSONL file handler
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = Path(log_dir) / f"{mode}_{now}.jsonl"
    jsonl_handler = _JsonlHandler(log_path)
    jsonl_handler.setLevel(logging.DEBUG)
    logger.addHandler(jsonl_handler)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(_ConsoleFormatter())
    logger.addHandler(console)

    return logger


def log_event(logger: logging.Logger, event: LogEvent):
    """Emit a structured LogEvent through the logger."""
    record = logger.makeRecord(
        name=logger.name,
        level=logging.INFO,
        fn="",
        lno=0,
        msg=event.event,
        args=(),
        exc_info=None,
    )
    record.log_event = event  # type: ignore[attr-defined]
    logger.handle(record)
