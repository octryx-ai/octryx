from __future__ import annotations

from pathlib import Path

import pytest

from app.exceptions.base import ExecutionRuntimeUnavailableError
from app.services.lsp import LspClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "expected_message"),
    [
        (OSError("spawn failed"), "lsp_start_failed error_type=OSError"),
        (ValueError("bad runtime config"), "lsp_start_failed error_type=ValueError"),
        (
            ExecutionRuntimeUnavailableError("runtime unavailable"),
            "lsp_start_failed error_type=ExecutionRuntimeUnavailableError",
        ),
    ],
)
async def test_lsp_client_start_returns_false_for_expected_spawn_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    raised: Exception,
    expected_message: str,
) -> None:
    async def fake_spawn(**_: object) -> object:
        raise raised

    monkeypatch.setattr("app.services.lsp.wiring.spawn_persistent_stdio_process", fake_spawn)
    monkeypatch.setattr("app.services.lsp.wiring.shutil.which", lambda _binary: "/usr/bin/pylsp")

    client = LspClient("python", str(tmp_path))

    with caplog.at_level("WARNING"):
        started = await client.start()

    assert started is False
    assert expected_message in caplog.text
    # The exception message is never logged, only its class name.
    assert str(raised) not in caplog.text


@pytest.mark.asyncio
async def test_lsp_client_start_propagates_unexpected_spawn_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_spawn(**_: object) -> object:
        raise KeyError("unexpected programming error")

    monkeypatch.setattr("app.services.lsp.wiring.spawn_persistent_stdio_process", fake_spawn)
    monkeypatch.setattr("app.services.lsp.wiring.shutil.which", lambda _binary: "/usr/bin/pylsp")

    client = LspClient("python", str(tmp_path))

    with pytest.raises(KeyError, match="unexpected programming error"):
        await client.start()
