"""The Docling sandbox adapter of the parser port.

The sandbox is ``docling-serve`` pinned by image digest, running in a container **without any
network** (``network_mode: none`` locally). Its only channel is a Unix socket on a volume shared
with the API, so it cannot fetch a URL a document points to and cannot send a document anywhere.

Fixed parse profile (:data:`PARSE_PROFILE`): JSON output only, pictures as placeholders (no
image bytes), OCR for scanned pages, accurate table structure, and the ``pypdfium2`` PDF backend,
which keeps word spacing that the default backend loses on LaTeX-produced PDFs (measured). The
profile is part of the parser identity recorded on every revision, so a changed profile is a
changed parser. Two per-request options vary it: ``do_ocr`` (off for a born-digital PDF;
the choice is recorded in the revision's parser version, ``ocr_choice.py``) and the text-layer probe
(a ``page_range``, with table structure off because the probe only counts text).

Before a submission the adapter checks that the sandbox runs the pinned ``docling-serve``
version; a different one is a contract violation, never a silent re-parse with other models.
Every response is bounded and every failure is mapped to the port's fixed taxonomy; no sandbox
text leaves this module.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from .parser_port import ParserError, ParserIdentity, ParserState, TaskStatus

logger = logging.getLogger(__name__)

SOCKET_ENV = "OCTRYX_KNOWLEDGE_PARSER_SOCKET"
VERSION_ENV = "OCTRYX_KNOWLEDGE_PARSER_VERSION"
API_KEY_ENV = "OCTRYX_KNOWLEDGE_PARSER_API_KEY"

PARSER_NAME = "docling-serve"
PARSER_SANDBOX = "no_network_uds"
PROFILE_TAG = "p1"
PARSE_PROFILE: dict[str, str] = {
    "to_formats": "json",
    "image_export_mode": "placeholder",
    "do_ocr": "true",
    "table_mode": "accurate",
    "pdf_backend": "pypdfium2",
    "abort_on_error": "false",
}
# The file name the sandbox sees; fixed per media type, never the uploader's name.
_FILE_NAMES = {
    "text/html": "source.html",
    "application/pdf": "source.pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "source.docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "source.pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "source.xlsx",
}
MAX_RESULT_BYTES = 64 * 1024 * 1024
MAX_SMALL_RESPONSE_BYTES = 64 * 1024
_SOCKET_PATH = re.compile(r"^/[A-Za-z0-9._/-]{1,100}$")
_VERSION = re.compile(r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$")
_TASK_REF = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_API_KEY = re.compile(r"^[\x21-\x7e]{16,256}$")
_TIMEOUT = httpx.Timeout(60.0, connect=5.0)
_ACCEPTED_RESULT_STATES = frozenset({"success", "partial_success"})


@dataclass(frozen=True, slots=True)
class DoclingSandboxConfig:
    socket_path: str
    version: str
    api_key: str | None = None

    def __repr__(self) -> str:
        return "DoclingSandboxConfig(configured=True)"


def docling_config_from_environment(environ: Mapping[str, str]) -> DoclingSandboxConfig:
    """The sandbox configuration, or the fixed ``needs_configuration`` state."""
    socket_path = (environ.get(SOCKET_ENV) or "").strip()
    version = (environ.get(VERSION_ENV) or "").strip()
    if not socket_path and not version:
        raise ParserError(ParserState.NEEDS_CONFIGURATION, "parser_not_configured")
    if not _SOCKET_PATH.fullmatch(socket_path) or ".." in socket_path.split("/"):
        raise ParserError(ParserState.NEEDS_CONFIGURATION, "socket_invalid")
    if not _VERSION.fullmatch(version):
        raise ParserError(ParserState.NEEDS_CONFIGURATION, "version_invalid")
    api_key = (environ.get(API_KEY_ENV) or "").strip() or None
    if api_key is not None and not _API_KEY.fullmatch(api_key):
        raise ParserError(ParserState.NEEDS_CONFIGURATION, "api_key_invalid")
    return DoclingSandboxConfig(socket_path=socket_path, version=version, api_key=api_key)


def _task_ref(value: object) -> str:
    if type(value) is not str or not _TASK_REF.fullmatch(value):
        raise ParserError(ParserState.CONTRACT_VIOLATION, "task_ref")
    return value


class DoclingSandboxParser:
    """``DocumentParser`` over the sandbox's Unix socket."""

    def __init__(self, config: DoclingSandboxConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._config = config
        self._identity = ParserIdentity(
            name=PARSER_NAME, version=f"{config.version}+{PROFILE_TAG}", sandbox=PARSER_SANDBOX
        )
        headers = {"X-Api-Key": config.api_key} if config.api_key else {}
        self._client = httpx.AsyncClient(
            transport=transport or httpx.AsyncHTTPTransport(uds=config.socket_path),
            base_url="http://docling-sandbox",
            headers=headers,
            timeout=_TIMEOUT,
            follow_redirects=False,
        )

    @property
    def identity(self) -> ParserIdentity:
        return self._identity

    async def _get(self, path: str, *, limit: int) -> tuple[int, bytes]:
        try:
            async with self._client.stream("GET", path) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise ParserError(ParserState.CONTRACT_VIOLATION, "response_too_large")
                return response.status_code, bytes(body)
        except httpx.HTTPError:
            raise ParserError(ParserState.UNAVAILABLE, "transport") from None

    @staticmethod
    def _json(status: int, body: bytes) -> dict[str, Any]:
        if status in (401, 403):
            raise ParserError(ParserState.NEEDS_CONFIGURATION, "unauthorized")
        if status >= 500:
            raise ParserError(ParserState.UNAVAILABLE, "server_error")
        if status != 200:
            raise ParserError(ParserState.CONTRACT_VIOLATION, "status")
        try:
            value = json.loads(body)
        except ValueError:
            raise ParserError(ParserState.CONTRACT_VIOLATION, "json") from None
        if not isinstance(value, dict):
            raise ParserError(ParserState.CONTRACT_VIOLATION, "json")
        return value

    async def _require_pinned_version(self) -> None:
        version = self._json(*await self._get("/version", limit=MAX_SMALL_RESPONSE_BYTES)).get(PARSER_NAME)
        if version != self._config.version:
            logger.warning("Knowledge parser sandbox runs an unpinned version")
            raise ParserError(ParserState.CONTRACT_VIOLATION, "version_mismatch")

    async def submit(
        self, data: bytes, media_type: str, *, do_ocr: bool = True, page_range: tuple[int, int] | None = None
    ) -> str:
        file_name = _FILE_NAMES.get(media_type)
        if file_name is None or type(data) is not bytes or not data or type(do_ocr) is not bool:
            raise ParserError(ParserState.CONTRACT_VIOLATION, "submission")
        form: dict[str, str | list[str]] = {**PARSE_PROFILE, "do_ocr": "true" if do_ocr else "false"}
        if page_range is not None:
            first, last = page_range
            if type(first) is not int or type(last) is not int or not 1 <= first <= last:
                raise ParserError(ParserState.CONTRACT_VIOLATION, "submission")
            form.update(page_range=[str(first), str(last)], do_table_structure="false")
        await self._require_pinned_version()
        try:
            response = await self._client.post(
                "/v1/convert/file/async", files={"files": (file_name, data, media_type)}, data=form
            )
        except httpx.HTTPError:
            raise ParserError(ParserState.UNAVAILABLE, "transport") from None
        if len(response.content) > MAX_SMALL_RESPONSE_BYTES:
            raise ParserError(ParserState.CONTRACT_VIOLATION, "response_too_large")
        return _task_ref(self._json(response.status_code, response.content).get("task_id"))

    async def poll(self, task_ref: str) -> TaskStatus:
        status, body = await self._get(f"/v1/status/poll/{_task_ref(task_ref)}", limit=MAX_SMALL_RESPONSE_BYTES)
        if status == 404:
            return TaskStatus.LOST
        state = self._json(status, body).get("task_status")
        if state in ("pending", "started"):
            return TaskStatus.PENDING
        if state == "success":
            return TaskStatus.SUCCESS
        if state == "failure":
            return TaskStatus.FAILURE
        raise ParserError(ParserState.CONTRACT_VIOLATION, "task_status")

    async def result(self, task_ref: str) -> dict[str, Any]:
        status, body = await self._get(f"/v1/result/{_task_ref(task_ref)}", limit=MAX_RESULT_BYTES)
        if status == 404:
            raise ParserError(ParserState.UNAVAILABLE, "result_gone")
        answer = self._json(status, body)
        if answer.get("status") not in _ACCEPTED_RESULT_STATES:
            raise ParserError(ParserState.REFUSED, "conversion_failed")
        document = answer.get("document")
        content = document.get("json_content") if isinstance(document, dict) else None
        if not isinstance(content, dict):
            raise ParserError(ParserState.CONTRACT_VIOLATION, "document")
        if answer.get("status") == "partial_success":
            # Some pages failed; what was parsed is still evidence, and the log says it is partial.
            logger.warning("Knowledge parser sandbox returned a partial conversion")
        return content


__all__ = [
    "DoclingSandboxConfig",
    "DoclingSandboxParser",
    "PARSE_PROFILE",
    "docling_config_from_environment",
]
