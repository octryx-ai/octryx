from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from ..redaction_policy import redact_secret_payload, redact_secret_text
from ..request_context import get_current_request_id

_RESERVED_LOG_RECORD_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


def _record_metadata(record: logging.LogRecord) -> dict[str, object]:
    metadata = {
        key: value
        for key, value in record.__dict__.items()
        if key not in _RESERVED_LOG_RECORD_ATTRS and not key.startswith("_")
    }
    return redact_secret_payload(metadata, max_string_length=1000)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secret_text(record.getMessage(), max_chars=2000),
            "request_id": get_current_request_id() or "",
        }
        metadata = _record_metadata(record)
        if metadata:
            payload["metadata"] = metadata
        if record.exc_info:
            payload["exception"] = redact_secret_text(self.formatException(record.exc_info), max_chars=4000)
        return json.dumps(payload, ensure_ascii=True, default=str)


class RedactingTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_secret_text(super().format(record))


def configure_json_logging() -> None:
    formatter = JsonLogFormatter()
    _give_root_a_handler(formatter)
    logger_names = ("", "uvicorn", "uvicorn.error", "uvicorn.access")
    for logger_name in logger_names:
        logger = logging.getLogger(logger_name)
        if not logger.handlers:
            continue
        for handler in logger.handlers:
            handler.setFormatter(formatter)

    # Suppress SQLAlchemy query echo regardless of debug mode.
    # Set engine to WARNING so individual SQL statements stay out of the log
    # while schema errors and connection problems still surface.
    warning_level = getattr(logging, "WARNING", 30)
    # httpx logs every request URL at INFO, and some APIs carry the credential in the URL (the Telegram Bot API).
    for logger_name in ("sqlalchemy.engine", "sqlalchemy.pool", "httpx"):
        try:
            logger = logging.getLogger(logger_name)
        except (KeyError, AttributeError):
            continue
        set_level = getattr(logger, "setLevel", None)
        if callable(set_level):
            set_level(warning_level)


def configure_text_logging(level: str) -> None:
    logging.basicConfig(level=level)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(RedactingTextFormatter(logging.BASIC_FORMAT))


def _give_root_a_handler(formatter: logging.Formatter) -> None:
    root = logging.getLogger()
    # Without one, records end in Python's last-resort handler, which never redacts. A root that has handlers (a
    # process's own setup) keeps them, so no line is written twice.
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
