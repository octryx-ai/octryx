"""A real render proves the isolation: a linked external image is not fetched, the no-network wrapper itself takes the network away, and the sidecar modules import nothing of the application."""

from __future__ import annotations

import shutil
import socket
import stat
import tempfile
import threading
from pathlib import Path

import pytest

from app.services.office import render, render_sandbox, render_server
from app.services.office.render_sandbox import RenderError


def _linked_image_docx(path: Path, url: str) -> Path:
    from docx import Document
    from docx.oxml import parse_xml

    document = Document()
    document.add_paragraph("A linked picture follows.")
    rid = document.part.relate_to(
        url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", is_external=True
    )
    document.add_paragraph()._p.append(parse_xml(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:drawing>'
        '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        '<wp:extent cx="914400" cy="914400"/><wp:docPr id="9" name="linked"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr><pic:cNvPr id="9" name="linked"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        f'r:link="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm>'
        '<a:prstGeom prst="rect"/></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>'
    ))
    document.save(path)
    return path


@pytest.mark.skipif(
    render_sandbox.libreoffice_binary() is None or render_sandbox.isolation_prefix() is None,
    reason="needs LibreOffice and a no-network wrapper (unshare/sandbox-exec) on this machine",
)
async def test_a_linked_external_image_is_not_fetched(tmp_path, monkeypatch):
    monkeypatch.delenv(render.SOCKET_ENV, raising=False)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    listener.settimeout(0.5)
    port = listener.getsockname()[1]
    connections: list[str] = []
    done = threading.Event()

    def accept() -> None:
        while not done.is_set():
            try:
                connection, _ = listener.accept()
            except OSError:
                continue
            connections.append("connected")
            connection.close()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        document = _linked_image_docx(tmp_path / "linked.docx", f"http://127.0.0.1:{port}/probe.png")
        pdf = await render.render_office_document(document, "pdf")
    finally:
        done.set()
        thread.join(timeout=2)
        listener.close()
    assert pdf.startswith(b"%PDF")
    assert connections == []


@pytest.mark.skipif(render_sandbox.isolation_prefix() is None, reason="needs a no-network wrapper on this machine")
async def test_the_wrapper_itself_takes_the_network_away(tmp_path):
    import sys

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    port = listener.getsockname()[1]
    outcome = Path(tempfile.mkdtemp(prefix="octryx-net-", dir="/tmp")) / "outcome"
    probe = tmp_path / "probe"
    probe.write_text(
        f"#!{sys.executable}\nimport socket\n"
        f"try:\n    socket.create_connection(('127.0.0.1', {port}), timeout=3).close(); result = 'connected'\n"
        f"except OSError:\n    result = 'blocked'\nopen({str(outcome)!r}, 'w').write(result)\n",
        encoding="utf-8",
    )
    probe.chmod(probe.stat().st_mode | stat.S_IEXEC)
    try:
        for prefix, expected in ((render_sandbox.isolation_prefix(), "blocked"), ([], "connected")):
            outcome.unlink(missing_ok=True)
            with pytest.raises(RenderError):
                await render_sandbox.convert(b"PK", ".docx", binary=str(probe), prefix=prefix, timeout_sec=20)
            assert outcome.read_text() == expected
    finally:
        listener.close()
        shutil.rmtree(outcome.parent, ignore_errors=True)


def test_the_sidecar_modules_import_nothing_of_the_application():
    import ast

    for module in (render_sandbox, render_server):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 1 and node.module in (None, "render_sandbox") or node.level == 0 and not (
                    node.module or ""
                ).startswith("app"), f"{module.__name__} imports {node.module}"
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("app") for alias in node.names)
