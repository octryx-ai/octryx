"""Secret scan of a git bundle (handoff attachments)."""

from __future__ import annotations

import zlib

from ..model_gateway.inbound.secret_scan import contains_secret

MAX_INFLATED_BYTES = 512 * 1024 * 1024
MAX_OBJECTS = 200_000
CODE_SECRET = "secret_detected"
CODE_INVALID = "bundle_invalid"
CODE_TOO_LARGE = "bundle_too_large_unpacked"
_HEADERS = (b"# v2 git bundle\n", b"# v3 git bundle\n")
_BLOB, _OFS_DELTA, _REF_DELTA = 3, 6, 7
_CHUNK = 16 * 1024


def _pack_start(data: bytes) -> int:
    if not data.startswith(_HEADERS):
        raise ValueError
    position = data.index(b"\n") + 1
    while True:
        end = data.index(b"\n", position)
        if end == position:  # the blank line ends the header
            return end + 1
        position = end + 1


def _varint_type_size(data: bytes, position: int) -> tuple[int, int]:
    byte = data[position]
    kind = (byte >> 4) & 7
    position += 1
    while byte & 0x80:
        byte = data[position]
        position += 1
    return kind, position


def _skip_offset(data: bytes, position: int) -> int:
    byte = data[position]
    position += 1
    while byte & 0x80:
        byte = data[position]
        position += 1
    return position


def _inflate(view: memoryview, position: int, budget: int) -> tuple[bytes, int]:
    stream = zlib.decompressobj()
    content = bytearray()
    while not stream.eof:
        chunk = view[position:position + _CHUNK]
        if not chunk:
            raise ValueError  # truncated pack
        content += stream.decompress(chunk)
        if len(content) > budget:
            raise OverflowError
        position += len(chunk) - len(stream.unused_data) if stream.eof else len(chunk)
    return bytes(content), position


def scan_bundle(data: bytes) -> str:
    view = memoryview(data)
    try:
        position = _pack_start(data)
        if data[position:position + 4] != b"PACK":
            return CODE_INVALID
        count = int.from_bytes(data[position + 8:position + 12], "big")
        if count > MAX_OBJECTS:
            return CODE_TOO_LARGE
        position += 12
        inflated = 0
        for _ in range(count):
            kind, position = _varint_type_size(data, position)
            if kind == _OFS_DELTA:
                position = _skip_offset(data, position)
            elif kind == _REF_DELTA:
                position += 20
            content, position = _inflate(view, position, MAX_INFLATED_BYTES - inflated)
            inflated += len(content)
            if kind in (_BLOB, _OFS_DELTA, _REF_DELTA) and contains_secret(content.decode("utf-8", "replace")):
                return CODE_SECRET
    except OverflowError:
        return CODE_TOO_LARGE
    except (ValueError, IndexError, zlib.error):
        return CODE_INVALID
    return ""


__all__ = ["CODE_INVALID", "CODE_SECRET", "CODE_TOO_LARGE", "scan_bundle"]
