"""Media-type policy of the Evidence ledger.

Two classes of documents are accepted, and everything else is refused:

- **text-native** types this process parses in-process, without a subprocess or a sandbox escape:
  ``txt``, ``md``, ``adoc``, ``csv``, ``json`` and ``xml``;
- **sandboxed** types that only the no-network Docling sandbox parses: HTML, PDF and the Office
  Open XML formats (``docx``, ``pptx``, ``xlsx``). The API process never parses these bytes.

Images, archives and legacy binary formats return the typed ``unsupported_media_type`` state
*before any object write*, so an unsupported upload leaves no bytes and no ledger row behind.

The decision is deny-by-default and is made on two independent inputs:

1. the **declared** content type, normalized to a bare type/subtype; and
2. a **sniff** of the leading bytes, which rejects the well-known binary magic
   numbers even when the declared type claims text.

Both must pass. A declared type that is absent, unknown, or parameterized in an
unexpected way is a refusal, never a guess from the file name: the file name is
attacker-controlled and is not consulted at all.
"""

from __future__ import annotations

import re

from ..ledger.errors import InvalidEvidenceRequestError, UnsupportedMediaTypeError

MAX_MEDIA_TYPE_CHARS = 120
PARSER_NAME = "text_native"
PARSER_VERSION = "1"
# Recorded in the ledger as lineage: this parser runs in the API process, so a
# later sandboxed parser is distinguishable from what produced these spans.
PARSER_SANDBOX = "in_process"

# Canonical media types accepted by this slice, mapped to the ledger's stored value.
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

# Media types the sandboxed parser owns, mapped to the ledger's stored value and to the
# leading bytes the payload must start with. The two checks are independent, as above: a declared
# PDF that is not a PDF is refused, and so is a PDF declared as a Word document.
SANDBOXED_MEDIA_TYPES: dict[str, tuple[str, bytes]] = {
    "application/pdf": ("application/pdf", b"%PDF-"),
    # HTML has no magic number; it must still not look binary. Docling keeps its headings and tables,
    # which a plain-text split would bury in markup.
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
    b"%PDF-",  # PDF
    b"PK\x03\x04",  # zip container: Office Open XML, ODF, jar
    b"\xd0\xcf\x11\xe0",  # legacy OLE compound file: doc, xls, ppt
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",  # JPEG
    b"GIF87a",
    b"GIF89a",
    b"RIFF",  # WebP, WAV
    b"\x1f\x8b",  # gzip
    b"BZh",  # bzip2
    b"\xfd7zXZ\x00",  # xz
    b"7z\xbc\xaf\x27\x1c",  # 7-zip
    b"\x7fELF",
    b"MZ",  # PE
    b"\x00\x00\x01\x00",  # ICO
    b"{\\rtf",  # RTF
    b"SQLite format 3\x00",
)
_SNIFF_BYTES = 32


def normalize_media_type(declared: object) -> str:
    """Normalize a declared content type to a bare, lower-case ``type/subtype``."""
    if declared is None:
        raise UnsupportedMediaTypeError()
    if type(declared) is not str or not declared or len(declared) > MAX_MEDIA_TYPE_CHARS:
        raise InvalidEvidenceRequestError()
    # Control characters are refused on the *raw* header, before parameters are
    # dropped: a header carrying NUL or a line break is not a media type, and
    # dropping the parameter first would let it pass unnoticed.
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in declared):
        raise InvalidEvidenceRequestError()
    # Parameters (``; charset=utf-8``) are dropped; the bytes decide the encoding.
    bare = declared.split(";", 1)[0].strip().lower()
    if not _MEDIA_TYPE.fullmatch(bare):
        raise InvalidEvidenceRequestError()
    return bare


def looks_binary(data: bytes) -> bool:
    """True when the leading bytes are a known binary format or contain NUL."""
    if type(data) is not bytes:
        raise InvalidEvidenceRequestError()
    head = data[:_SNIFF_BYTES]
    if any(head.startswith(magic) for magic in _BINARY_MAGIC):
        return True
    # A NUL byte in the head is never valid in any accepted text type.
    return b"\x00" in head


def resolve_text_native_media_type(declared: object, data: bytes) -> str:
    """Return the stored media type, or refuse before anything is written.

    Deny-by-default: an unknown declared type and any binary-looking payload are
    both refusals, and the two checks are independent so neither can vouch for
    the other.
    """
    bare = normalize_media_type(declared)
    stored = TEXT_NATIVE_MEDIA_TYPES.get(bare)
    if stored is None:
        raise UnsupportedMediaTypeError()
    if looks_binary(data):
        raise UnsupportedMediaTypeError()
    return stored


def is_sandboxed_media_type(declared: object) -> bool:
    """True when the declared type belongs to the sandboxed parser. Never raises."""
    try:
        return normalize_media_type(declared) in SANDBOXED_MEDIA_TYPES
    except (InvalidEvidenceRequestError, UnsupportedMediaTypeError):
        return False


def resolve_sandboxed_media_type(declared: object, data: bytes) -> str:
    """Return the stored media type of a sandboxed document, or refuse before anything is written."""
    entry = SANDBOXED_MEDIA_TYPES.get(normalize_media_type(declared))
    if entry is None:
        raise UnsupportedMediaTypeError()
    stored, magic = entry
    if type(data) is not bytes or not data.startswith(magic):
        raise UnsupportedMediaTypeError()
    if not magic and looks_binary(data):
        raise UnsupportedMediaTypeError()
    return stored
