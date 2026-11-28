"""The JSON logging setup formats every handled logger exactly once."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
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


PROVIDER_KEY = "sk-proj-" + "Synthetic" * 4
TELEGRAM = "100000001:A" + "Synthetic_Telegram-" + "x" * 15
BEARER = "SyntheticBearerValue0001"
TOKENS = (PROVIDER_KEY, TELEGRAM, BEARER)


@contextmanager
def bare_root() -> Iterator[logging.Logger]:
    # The test runner adds its capture handlers to the root during the test call itself.
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    root.handlers = []
    try:
        yield root
    finally:
        root.handlers = saved
        root.setLevel(level)


def _captured(root: logging.Logger) -> io.StringIO:
    [handler] = root.handlers
    stream = io.StringIO()
    handler.setStream(stream)
    return stream


def _log_a_failure(logger_name: str) -> None:
    try:
        raise RuntimeError(f"refused key {PROVIDER_KEY} at https://api.telegram.org/bot{TELEGRAM}/getMe "
                           f"with Authorization: Bearer {BEARER}")
    except RuntimeError:
        logging.getLogger(logger_name).exception("call failed for %s", PROVIDER_KEY)


def test_an_app_error_with_tokens_is_redacted_in_the_emitted_message_and_traceback() -> None:
    with bare_root() as root:
        observability_logging.configure_json_logging()
        stream = _captured(root)
        _log_a_failure("app.services.planted_caller")
    [line] = stream.getvalue().splitlines()
    record = json.loads(line)
    assert record["level"] == "ERROR" and "RuntimeError" in record["exception"]
    assert not any(token in line for token in TOKENS)


def test_a_third_party_warning_is_redacted_too() -> None:
    with bare_root() as root:
        observability_logging.configure_json_logging()
        stream = _captured(root)
        logging.getLogger("httpx").warning("GET https://api.telegram.org/bot%s/getUpdates failed", TELEGRAM)
    assert "getUpdates failed" in stream.getvalue() and TELEGRAM not in stream.getvalue()


def test_the_root_gets_one_handler_and_keeps_one_a_process_set_up() -> None:
    with bare_root() as root:
        observability_logging.configure_json_logging()
        observability_logging.configure_json_logging()
        assert len(root.handlers) == 1
        own = logging.StreamHandler(io.StringIO())
        root.handlers = [own]
        observability_logging.configure_json_logging()
        assert root.handlers == [own] and isinstance(own.formatter, observability_logging.JsonLogFormatter)


def test_the_code_indexer_keeps_its_text_format_and_redacts() -> None:
    with bare_root() as root:
        observability_logging.configure_text_logging("INFO")
        stream = _captured(root)
        _log_a_failure("octryx.code_indexer")
    output = stream.getvalue()
    assert output.startswith("ERROR:octryx.code_indexer:call failed for ") and "Traceback" in output
    assert not any(token in output for token in TOKENS)
