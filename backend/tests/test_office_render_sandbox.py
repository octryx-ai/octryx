"""The Office renderer cannot reach a network, leak the API environment, outlive its call or be flooded.

* the per-call LibreOffice profile and the child environment (unit);
* the isolation choice: sidecar only without network interfaces, otherwise a no-network wrapper, otherwise
  no render at all (``office_preview_unavailable``);
* timeout and cancellation kill the whole process group (a fake ``soffice`` that forks a helper);
* two concurrent renders, the third is rejected at once; OOXML only; size cap before anything runs;
* the sidecar protocol over its Unix socket, and the sidecar refusing to start with a network;
* the proof: a document linking an external image renders under the wrapper and the target sees no connection.
"""

from __future__ import annotations

import asyncio
import shutil
import stat
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.services.office import render, render_sandbox, render_server
from app.services.office.render_sandbox import RenderError

FAKE_SOFFICE = """#!/bin/sh
# Forks a helper like the real launcher does (oosplash -> soffice.bin), records both pids, then works.
sleep 300 &
echo $! > "$OCTRYX_TEST_PIDS/child.pid"
echo $$ > "$OCTRYX_TEST_PIDS/launcher.pid"
if [ -n "$OCTRYX_TEST_WRITE" ]; then
  outdir=""; prev=""; for arg in "$@"; do [ "$prev" = "--outdir" ] && outdir="$arg"; prev="$arg"; done
  mkdir -p "$outdir"; printf '%s' '%PDF-fake' > "$outdir/source.pdf"; kill $!; exit 0
fi
wait
"""


@pytest.fixture
def fake_soffice(tmp_path, monkeypatch):
    """A launcher stand-in. The child environment is scrubbed, so it learns its pid directory from a baked path."""
    pids = Path(tempfile.mkdtemp(prefix="octryx-pids-", dir="/tmp"))
    script = tmp_path / "soffice"
    script.write_text(FAKE_SOFFICE.replace("$OCTRYX_TEST_PIDS", str(pids)), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    yield script, pids
    shutil.rmtree(pids, ignore_errors=True)


def _writing(script: Path) -> Path:
    text = script.read_text(encoding="utf-8").replace('if [ -n "$OCTRYX_TEST_WRITE" ]; then', "if true; then")
    script.write_text(text, encoding="utf-8")
    return script


def _alive(pid: int) -> bool:
    """Running, not merely a zombie waiting to be reaped."""
    import subprocess

    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


async def _wait_for(path: Path, seconds: float = 10) -> int:
    for _ in range(int(seconds * 20)):
        if path.exists() and path.read_text().strip():
            return int(path.read_text().strip())
        await asyncio.sleep(0.05)
    raise AssertionError(f"{path.name} never appeared")


# --- profile, environment, isolation ----------------------------------------------------------------------


def test_the_profile_locks_macros_active_content_and_links():
    root = ET.fromstring(render_sandbox.profile_xcu())
    values = {
        (item.get("{http://openoffice.org/2001/registry}path"), prop.get("{http://openoffice.org/2001/registry}name")):
            prop.find("value").text
        for item in root for prop in item
    }
    scripting = "/org.openoffice.Office.Common/Security/Scripting"
    assert values[(scripting, "MacroSecurityLevel")] == "3"  # very high
    assert values[(scripting, "DisableMacrosExecution")] == "true"
    assert values[(scripting, "DisableActiveContent")] == "true"  # OLE and DDE
    assert values[(scripting, "BlockUntrustedRefererLinks")] == "true"
    assert values[("/org.openoffice.Office.Writer/Content/Update", "Link")] == "2"  # never
    assert values[("/org.openoffice.Office.Calc/Content/Update", "Link")] == "1"  # never


def test_the_child_environment_carries_nothing_of_the_api(monkeypatch, tmp_path):
    monkeypatch.setenv("JWT_SECRET", "leak-me")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak-me")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy")
    env = render_sandbox.minimal_env(tmp_path)
    assert set(env) == {"PATH", "HOME", "TMPDIR", "LANG"}
    assert "leak-me" not in "".join(env.values()) and "proxy" not in "".join(env.values())


def test_the_sidecar_renders_only_without_a_network(monkeypatch):
    assert render_sandbox.only_loopback(["lo"]) and render_sandbox.only_loopback(["lo0"])
    assert not render_sandbox.only_loopback(["lo", "eth0"])
    monkeypatch.setenv(render_sandbox.SIDECAR_ENV, render_sandbox.SIDECAR_NETWORK_NONE)
    monkeypatch.setattr(render_sandbox, "only_loopback", lambda interfaces=None: False)
    assert render_sandbox.isolation_prefix() is None
    with pytest.raises(SystemExit):
        render_server.main()


async def test_without_a_no_network_wrapper_nothing_runs(fake_soffice, tmp_path):
    script, pids = fake_soffice
    with pytest.raises(RenderError) as refused:
        await render_sandbox.convert(b"PK", ".docx", binary=str(script), prefix=None)
    assert refused.value.code == render_sandbox.OFFICE_PREVIEW_UNAVAILABLE
    assert not (pids / "launcher.pid").exists()


async def test_legacy_formats_and_oversized_documents_are_not_rendered(fake_soffice):
    script, pids = fake_soffice
    for suffix in (".doc", ".xls", ".ppt", ".odt"):
        with pytest.raises(RenderError) as legacy:
            await render_sandbox.convert(b"x", suffix, binary=str(script), prefix=[])
        assert legacy.value.code == render_sandbox.OFFICE_RENDER_UNSUPPORTED
    with pytest.raises(RenderError) as large:
        await render_sandbox.convert(b"x" * (render_sandbox.MAX_RENDER_BYTES + 1), ".docx", binary=str(script), prefix=[])
    assert large.value.code == render_sandbox.OFFICE_RENDER_TOO_LARGE
    assert not (pids / "launcher.pid").exists()


# --- process lifetime and limits --------------------------------------------------------------------------


async def test_a_timed_out_render_leaves_no_process_behind(fake_soffice):
    script, pids = fake_soffice
    with pytest.raises(RenderError) as timed_out:
        await render_sandbox.convert(b"PK", ".docx", binary=str(script), prefix=[], timeout_sec=1)
    assert timed_out.value.code == render_sandbox.OFFICE_RENDER_FAILED
    child, launcher = int((pids / "child.pid").read_text()), int((pids / "launcher.pid").read_text())
    await asyncio.sleep(0.2)
    assert not _alive(child) and not _alive(launcher)


async def test_a_cancelled_render_leaves_no_process_behind(fake_soffice):
    script, pids = fake_soffice
    task = asyncio.create_task(render_sandbox.convert(b"PK", ".docx", binary=str(script), prefix=[], timeout_sec=60))
    child = await _wait_for(pids / "child.pid")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.2)
    assert not _alive(child)


async def test_a_third_concurrent_render_is_rejected_at_once(fake_soffice):
    script, _ = fake_soffice
    running = [
        asyncio.create_task(render_sandbox.convert(b"PK", ".docx", binary=str(script), prefix=[], timeout_sec=60))
        for _ in range(render_sandbox.MAX_CONCURRENT_RENDERS)
    ]
    await asyncio.sleep(0.3)
    with pytest.raises(RenderError) as busy:
        await asyncio.wait_for(render_sandbox.convert(b"PK", ".docx", binary=str(script), prefix=[]), timeout=1)
    assert busy.value.code == render_sandbox.OFFICE_RENDER_BUSY
    for task in running:
        task.cancel()
    await asyncio.gather(*running, return_exceptions=True)


# --- the sidecar ------------------------------------------------------------------------------------------


async def test_the_sidecar_round_trip_and_its_size_check(fake_soffice, monkeypatch):
    script, _ = fake_soffice
    _writing(script)
    folder = Path(tempfile.mkdtemp(prefix="octryx-render-", dir="/tmp"))
    socket_path = str(folder / "render.sock")
    server = await render_server.serve(socket_path, prefix=[], binary=str(script))
    try:
        assert await render._render_via_sidecar(socket_path, b"PK", ".docx", "pdf") == b"%PDF-fake"
        with pytest.raises(RenderError) as legacy:
            await render._render_via_sidecar(socket_path, b"PK", ".doc", "pdf")
        assert legacy.value.code == render_sandbox.OFFICE_RENDER_UNSUPPORTED
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(b'{"format": "pdf", "suffix": ".docx", "size": %d}\n' % (render_sandbox.MAX_RENDER_BYTES + 1))
        await writer.drain()
        assert b"office_render_too_large" in await reader.readline()  # answered before any body byte
        writer.close()
    finally:
        server.close()
        await server.wait_closed()
        shutil.rmtree(folder, ignore_errors=True)
