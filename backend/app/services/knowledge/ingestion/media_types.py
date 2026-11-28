"""Media-type policy of the Evidence ledger: text-native or sandboxed, everything else refused. The declared type and a
byte sniff must both pass; the file name is never read."""

from __future__ import annotations

import re

from ..ledger.errors import InvalidEvidenceRequestError, UnsupportedMediaTypeError

MAX_MEDIA_TYPE_CHARS = 120
PARSER_NAME = "text_native"
PARSER_VERSION = "1"
# Recorded as lineage, so a later sandboxed parser is distinguishable from what produced these spans.
PARSER_SANDBOX = "in_process"

TEXT_NATIVE_MEDIA_TYPES: dict[str, str] = {
    "text/plain": "text/plain",
    "text/markdown": "text/markdown",
    "text/x-markdown": "text/markdown",
    "text/asciidoc": "text/asciidoc",
    "text/x-asciidoc": "text/asciidoc",
    "text/csv": "text/csv",
    "text/xml": "application/xml",
    "application/json": "application/json",
    "application/xml": "application/xml",
}

# Media types the sandboxed parser owns, with the leading bytes the payload must start with.
SANDBOXED_MEDIA_TYPES: dict[str, tuple[str, bytes]] = {
    "application/pdf": ("application/pdf", b"%PDF-"),
    # HTML has no magic number; it must still not look binary.
    "text/html": ("text/html", b""),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"PK\x03\x04",
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        b"PK\x03\x04",
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        b"PK\x03\x04",
    ),
}

_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,63}$")

# Leading bytes of formats that need the sandboxed parser or are never text.
_BINARY_MAGIC: tuple[bytes, ...] = (
    b"%PDF-",
    b"PK\x03\x04",  # zip container: Office Open XML, ODF, jar
    b"\xd0\xcf\x11\xe0",  # legacy OLE compound file: doc, xls, ppt
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"RIFF",  # WebP, WAV
    b"\x1f\x8b",
    b"BZh",
    b"\xfd7zXZ\x00",
    b"7z\xbc\xaf\x27\x1c",
    b"\x7fELF",
    b"MZ",  # PE
    b"\x00\x00\x01\x00",  # ICO
    b"{\\rtf",
    b"SQLite format 3\x00",
)
_SNIFF_BYTES = 32


def normalize_media_type(declared: object) -> str:
    if declared is None:
        raise UnsupportedMediaTypeError()
    if type(declared) is not str or not declared or len(declared) > MAX_MEDIA_TYPE_CHARS:
        raise InvalidEvidenceRequestError()
    # Control characters are refused on the raw header: dropping the parameters first would let a NUL or a
    # line break pass unnoticed.
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in declared):
        raise InvalidEvidenceRequestError()
    # Parameters (``; charset=utf-8``) are dropped; the bytes decide the encoding.
    bare = declared.split(";", 1)[0].strip().lower()
    if not _MEDIA_TYPE.fullmatch(bare):
        raise InvalidEvidenceRequestError()
    return bare


def looks_binary(data: bytes) -> bool:
    if type(data) is not bytes:
        raise InvalidEvidenceRequestError()
    head = data[:_SNIFF_BYTES]
    if any(head.startswith(magic) for magic in _BINARY_MAGIC):
        return True
    # A NUL byte in the head is never valid in any accepted text type.
    return b"\x00" in head


def resolve_text_native_media_type(declared: object, data: bytes) -> str:
    # Deny by default; the two checks are independent so neither can vouch for the other.
    bare = normalize_media_type(declared)
    stored = TEXT_NATIVE_MEDIA_TYPES.get(bare)
    if stored is None:
        raise UnsupportedMediaTypeError()
    if looks_binary(data):
        raise UnsupportedMediaTypeError()
    return stored


def is_sandboxed_media_type(declared: object) -> bool:
    try:
        return normalize_media_type(declared) in SANDBOXED_MEDIA_TYPES
    except (InvalidEvidenceRequestError, UnsupportedMediaTypeError):
        return False


def resolve_sandboxed_media_type(declared: object, data: bytes) -> str:
    entry = SANDBOXED_MEDIA_TYPES.get(normalize_media_type(declared))
    if entry is None:
        raise UnsupportedMediaTypeError()
    stored, magic = entry
    if type(data) is not bytes or not data.startswith(magic):
        raise UnsupportedMediaTypeError()
    if not magic and looks_binary(data):
        raise UnsupportedMediaTypeError()
    return stored
