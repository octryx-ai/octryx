"""The device unpacks only regular files of an offered archive with its sha256, and runs a pinned tool on it with a
minimal environment: no token reaches a tool reading a stranger's code."""

from __future__ import annotations

import hashlib
import io
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace

from octryx_claude import tool_run, tree_archive


def _tar(members: list[tuple[tarfile.TarInfo, bytes]]) -> bytes:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        for info, body in members:
            archive.addfile(info, io.BytesIO(body) if body else None)
    return data.getvalue()


def _file(name: str, body: bytes = b"x") -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(body)
    return info, body


def _link(name: str, kind: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, "/etc/passwd"
    return info, b""


def test_only_regular_files_inside_the_folder_are_written(tmp_path):
    data = _tar([_file("src/app.py", b"print(1)\n"), _file("../escape.py"), _file("/abs.py"),
                 _link("evil", tarfile.SYMTYPE), _link("hard", tarfile.LNKTYPE)])
    written, refused = tree_archive.unpack(data, tmp_path / "tree")
    assert written == 1 and (tmp_path / "tree/src/app.py").read_text() == "print(1)\n"
    assert sorted(refused) == ["../escape.py", "/abs.py", "evil", "hard"]
    assert not (tmp_path / "escape.py").exists() and not (tmp_path / "tree/evil").exists()


def test_an_archive_with_another_sha256_is_never_unpacked(tmp_path, monkeypatch):
    data = _tar([_file("a.py")])
    monkeypatch.setattr(tree_archive, "_token", lambda _state: "t")
    monkeypatch.setattr(tree_archive, "_base", lambda _state: "https://octryx.example")
    http = SimpleNamespace(get=lambda url, headers: SimpleNamespace(status_code=200, content=data))
    item = {"url": "/api/v1/devices/archives/abc", "sha256": "0" * 64}
    assert tree_archive.fetch(None, item, tmp_path / "t", http=http) == (
        None, "the archive does not match its sha256; nothing was unpacked")
    folder, problem = tree_archive.fetch(None, {**item, "sha256": hashlib.sha256(data).hexdigest()}, tmp_path / "t",
                                         http=http)
    assert problem == "" and (folder / "a.py").exists()
    assert tree_archive.fetch(None, {"url": "https://elsewhere/x"}, tmp_path, http=http)[0] is None


def test_a_tool_runs_with_a_minimal_environment_and_its_report_file(monkeypatch):
    work = Path(tempfile.mkdtemp())
    script = work / "fake-tool"
    script.write_text('#!/bin/sh\nenv > env.txt\necho \'{"runs": []}\' > report.sarif\necho done\n')
    script.chmod(0o755)
    monkeypatch.setattr(tool_run, "_executable", lambda tool_id: str(script) if tool_id == "opengrep" else None)
    monkeypatch.setenv("OCTRYX_DEVICE_TOKEN", "secret-token")
    result = tool_run.run_tool("opengrep", ["--sarif"], cwd=work, timeout=10, outputs=["report.sarif", "../x"])
    assert result["status"] == "ok" and result["exit"] == 0 and result["stdout"].strip() == "done"
    assert result["files"] == {"report.sarif": '{"runs": []}\n'}
    seen = (work / "env.txt").read_text()
    assert "secret-token" not in seen and f"HOME={work.resolve()}" in seen
    assert set(line.split("=", 1)[0] for line in seen.splitlines()) <= {"PATH", "HOME", "LANG", "PWD", "SHLVL", "_"}
    assert tool_run.run_tool("gitleaks", [], cwd=work, timeout=5)["status"] == "missing"
    # a folder outside the temporary folder, wherever the checkout lives (a CI clone may sit under /tmp)
    assert tool_run.run_tool("opengrep", [], cwd=Path("/"), timeout=5)["status"] == "error"
