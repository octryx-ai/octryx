"""The Office render sidecar: LibreOffice behind a Unix socket, in a container without network.

Started by the acceptance stack as the ``office-render`` service (``network_mode: none``, own minimal
environment, no secrets, read-only root, capped memory and pids). Its only channel is the socket on the
volume it shares with the API. It refuses to start when it can see any network interface but loopback,
so a misconfigured deployment cannot turn it into a fetcher.

Wire format, one request per connection (stdlib only, no ``app.*`` import):

* request: one JSON line ``{"format": "pdf"|"png", "suffix": ".docx"|".xlsx"|".pptx", "size": N}`` then N bytes;
* response: one JSON line ``{"ok": true, "size": M}`` then M bytes, or ``{"ok": false, "code": "<closed code>"}``.

The size is checked against the cap before a byte of the body is read.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from . import render_sandbox as sandbox

SOCKET_ENV = "OCTRYX_RENDER_SOCKET"
DEFAULT_SOCKET = "/run/octryx-render/render.sock"
MAX_HEADER_BYTES = 1024


async def _reply(writer: asyncio.StreamWriter, header: dict, body: bytes = b"") -> None:
    writer.write(json.dumps(header).encode() + b"\n" + body)
    await writer.drain()
    writer.close()


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, prefix: list[str] | None,
                 binary: str | None = None) -> None:
    try:
        line = await reader.readuntil(b"\n")
        if len(line) > MAX_HEADER_BYTES:
            raise sandbox.RenderError(sandbox.OFFICE_RENDER_FAILED, "header")
        request = json.loads(line)
        size = int(request.get("size") or 0)
        suffix, fmt = str(request.get("suffix") or ""), str(request.get("format") or "pdf")
        sandbox.check_request(suffix, size, fmt)
        data = await reader.readexactly(size)
        rendered = await sandbox.convert(data, suffix, fmt, binary=binary, prefix=prefix)
    except sandbox.RenderError as exc:
        await _reply(writer, {"ok": False, "code": exc.code})
        return
    except (ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        await _reply(writer, {"ok": False, "code": sandbox.OFFICE_RENDER_FAILED})
        return
    await _reply(writer, {"ok": True, "size": len(rendered)}, rendered)


async def serve(socket_path: str, *, prefix: list[str] | None, binary: str | None = None) -> asyncio.AbstractServer:
    path = Path(socket_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    server = await asyncio.start_unix_server(
        lambda r, w: handle(r, w, prefix=prefix, binary=binary), path=str(path), limit=MAX_HEADER_BYTES * 2
    )
    os.chmod(path, 0o660)
    return server


def main() -> None:
    if not sandbox.only_loopback():
        sys.exit("office-render: a network interface is visible; refusing to render (needs network_mode: none)")
    os.environ[sandbox.SIDECAR_ENV] = sandbox.SIDECAR_NETWORK_NONE

    async def run() -> None:
        server = await serve(os.environ.get(SOCKET_ENV, DEFAULT_SOCKET), prefix=[])
        async with server:
            await server.serve_forever()

    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
