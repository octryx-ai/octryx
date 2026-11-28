"""Server-sent-event framing shared by the inbound relays and observers (``anthropic_stream``, ``responses_stream``,
the seat observers)."""

from __future__ import annotations

_BOUNDARIES = (b"\r\n\r\n", b"\n\n")


def split_sse_event(buffer: bytes) -> tuple[bytes, bytes] | None:
    found: tuple[int, int] | None = None
    for boundary in _BOUNDARIES:
        index = buffer.find(boundary)
        if index >= 0 and (found is None or index < found[0]):
            found = (index, len(boundary))
    if found is None:
        return None
    end = found[0] + found[1]
    return buffer[:end], buffer[end:]


def sse_event_fields(raw: bytes) -> tuple[str, str]:
    name = ""
    data_lines: list[str] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
    return name, "\n".join(data_lines)


__all__ = ["split_sse_event", "sse_event_fields"]
