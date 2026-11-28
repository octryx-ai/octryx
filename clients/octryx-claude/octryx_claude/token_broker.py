"""Short-lived model-gateway and MCP tokens for a server runner's agent account, on a socket of the launcher;
never the device channel's token or the refresh token."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
from pathlib import Path

from .tokens import GATEWAY_AUDIENCE, MCP_AUDIENCE, TokenUnavailableError

SOCKET_ENV = "OCTRYX_TOKEN_SOCKET"
ALLOWED_AUDIENCES = (GATEWAY_AUDIENCE, MCP_AUDIENCE)
MAX_REQUEST_BYTES = 1024
TIMEOUT_SECONDS = 30.0


async def serve(state, path: Path, stop: asyncio.Event) -> None:
    from .tokens import get_access_token  # noqa: PLC0415

    async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        reply: dict = {"error": "invalid_request"}
        with contextlib.suppress(Exception):
            request = json.loads(await asyncio.wait_for(reader.readline(), TIMEOUT_SECONDS) or b"{}")
            audience = str(request.get("audience") or "")
            if audience in ALLOWED_AUDIENCES:
                import httpx  # noqa: PLC0415

                def fetch() -> str:
                    with httpx.Client() as http:
                        return get_access_token(state, audience, http=http)

                try:
                    reply = {"token": await asyncio.to_thread(fetch)}
                except TokenUnavailableError as exc:
                    reply = {"error": exc.code}
            else:
                reply = {"error": "audience_not_allowed"}
        with contextlib.suppress(Exception):
            writer.write((json.dumps(reply) + "\n").encode())
            await writer.drain()
            writer.close()

    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    server = await asyncio.start_unix_server(answer, path=str(path))
    os.chmod(path, 0o660)
    try:
        await stop.wait()
    finally:
        server.close()
        await server.wait_closed()
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def broker_path() -> str:
    return os.environ.get(SOCKET_ENV, "")


def request_token(audience: str, path: str) -> str:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(TIMEOUT_SECONDS)
            client.connect(path)
            client.sendall((json.dumps({"audience": audience}) + "\n").encode())
            raw = b""
            while not raw.endswith(b"\n") and len(raw) < 64 * 1024:
                chunk = client.recv(4096)
                if not chunk:
                    break
                raw += chunk
        reply = json.loads(raw or b"{}")
    except (OSError, ValueError) as exc:
        raise TokenUnavailableError("token_broker_unreachable") from exc
    token = reply.get("token") if isinstance(reply, dict) else None
    if not isinstance(token, str) or not token:
        raise TokenUnavailableError(str((reply or {}).get("error") or "token_broker_refused")[:64])
    return token


__all__ = ["ALLOWED_AUDIENCES", "SOCKET_ENV", "broker_path", "request_token", "serve"]
