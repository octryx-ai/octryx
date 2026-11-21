"""The JSON logging setup formats every handled logger exactly once."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from app.services.observability import logging as observability_logging


def test_configure_json_logging_preserves_current_handler_selection(monkeypatch) -> None:
    assigned_formatters: dict[str, list[logging.Formatter]] = {}

    class RecordingHandler:
        def __init__(self, logger_name: str) -> None:
            self._logger_name = logger_name

        def setFormatter(self, formatter: logging.Formatter) -> None:  # noqa: N802
            assigned_formatters.setdefault(self._logger_name, []).append(formatter)

    class FakeLogger:
        def __init__(self, handlers: list[RecordingHandler]) -> None:
            self.handlers = handlers

    fake_loggers = {
        "": FakeLogger([RecordingHandler("")]),
        "uvicorn": FakeLogger([RecordingHandler("uvicorn")]),
        "uvicorn.error": FakeLogger([]),
        "uvicorn.access": FakeLogger([RecordingHandler("uvicorn.access")]),
    }

    def fake_get_logger(name: str = "") -> FakeLogger:
        return fake_loggers[name]

    monkeypatch.setitem(
        observability_logging.configure_json_logging.__globals__,
        "logging",
        SimpleNamespace(getLogger=fake_get_logger),
    )

    observability_logging.configure_json_logging()

    assert set(assigned_formatters) == {"", "uvicorn", "uvicorn.access"}
    for formatters in assigned_formatters.values():
        assert len(formatters) == 1
        assert isinstance(formatters[0], observability_logging.JsonLogFormatter)
