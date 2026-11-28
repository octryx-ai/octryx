"""Voice-based speaker enrollment via Teams call."""

from __future__ import annotations

import io
import logging
import math
import re
import struct
import wave
from dataclasses import dataclass
from enum import Enum, auto

from ..person_log_ref import person_log_ref

logger = logging.getLogger(__name__)

# Placeholder name when caller identity isn't available from Graph
_UNKNOWN_CALLER_PLACEHOLDER = "__CALLER__"

_ENROLL_PATTERNS_WITH_NAME = [
    re.compile(r"register\s+(?:my\s+)?voice\s+(?:as|for)\s+(.+)", re.IGNORECASE),
    re.compile(r"enroll\s+(?:my\s+)?voice\s+(?:as|for)\s+(.+)", re.IGNORECASE),
    re.compile(r"save\s+(?:my\s+)?voice\s+(?:as|for)\s+(.+)", re.IGNORECASE),
    re.compile(r"record\s+(?:my\s+)?voice\s+(?:as|for)\s+(.+)", re.IGNORECASE),
]

_ENROLL_PATTERNS_NO_NAME = [
    re.compile(r"register\s+(?:my\s+)?voice", re.IGNORECASE),
    re.compile(r"enroll\s+(?:my\s+)?voice", re.IGNORECASE),
    re.compile(r"save\s+(?:my\s+)?voice", re.IGNORECASE),
    re.compile(r"record\s+(?:my\s+)?voice", re.IGNORECASE),
]

# Catches common Whisper mis-transcriptions like "rest of my voice" for "register my voice"
_ENROLL_FUZZY_KEYWORDS = [
    "register",
    "voice",
    "enroll",
    "save",
    "rest",
    "my voice",
]


class EnrollmentState(Enum):
    """State machine for the enrollment flow."""

    IDLE = auto()
    AWAITING_SAMPLE = auto()


@dataclass
class EnrollmentSession:
    speaker_name: str
    project_id: str
    state: EnrollmentState = EnrollmentState.AWAITING_SAMPLE
    call_id: str = ""


_enrollment_sessions: dict[str, EnrollmentSession] = {}


def detect_enrollment_command(command_text: str, caller_display_name: str = "") -> str | None:
    text = command_text.strip()

    for pattern in _ENROLL_PATTERNS_WITH_NAME:
        match = pattern.search(text)
        if match:
            name = match.group(1).strip().rstrip(".!?,;:")
            name = re.sub(r"\bplease\b", "", name, flags=re.IGNORECASE).strip()
            if name and len(name) < 50:
                return name

    for pattern in _ENROLL_PATTERNS_NO_NAME:
        if pattern.search(text):
            if caller_display_name and caller_display_name.strip():
                return caller_display_name.strip()
            # The placeholder makes the flow ask for the name.
            return _UNKNOWN_CALLER_PLACEHOLDER

    # Whisper often garbles "register my voice" (e.g. "rest of my voice"), so "voice" plus a keyword suffices.
    text_lower = text.lower()
    has_voice = "voice" in text_lower
    has_register_keyword = any(
        kw in text_lower for kw in ("register", "regist", "enroll", "save", "record", "rest")
    )
    if has_voice and has_register_keyword:
        if caller_display_name and caller_display_name.strip():
            logger.info("Fuzzy enrollment match: chars=%d → name=%s", len(text), person_log_ref(caller_display_name))
            return caller_display_name.strip()
        return _UNKNOWN_CALLER_PLACEHOLDER

    return None


def start_enrollment(call_id: str, speaker_name: str, project_id: str) -> EnrollmentSession:
    session = EnrollmentSession(
        speaker_name=speaker_name,
        project_id=project_id,
        state=EnrollmentState.AWAITING_SAMPLE,
        call_id=call_id,
    )
    _enrollment_sessions[call_id] = session
    logger.info("Started voice enrollment for %s on call %s", person_log_ref(speaker_name), call_id)
    return session


def get_enrollment_session(call_id: str) -> EnrollmentSession | None:
    return _enrollment_sessions.get(call_id)


def complete_enrollment(call_id: str) -> EnrollmentSession | None:
    return _enrollment_sessions.pop(call_id, None)


def generate_beep(
    frequency: float = 880.0,
    duration_sec: float = 0.5,
    sample_rate: int = 16000,
    volume: float = 0.6,
) -> bytes:
    n_samples = int(sample_rate * duration_sec)
    samples = []

    for i in range(n_samples):
        t = i / sample_rate
        # Sine wave with a slight fade-in/out to avoid clicks
        fade_samples = int(sample_rate * 0.02)
        amplitude = volume
        if i < fade_samples:
            amplitude *= i / fade_samples
        elif i > n_samples - fade_samples:
            amplitude *= (n_samples - i) / fade_samples

        sample = amplitude * math.sin(2 * math.pi * frequency * t)
        samples.append(int(sample * 32767))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    return buf.getvalue()


def get_enrollment_instruction_text(speaker_name: str) -> str:
    return (
        f"Okay {speaker_name}, I'll register your voice now. "
        f"Please talk freely after the beep. "
        f"Keep talking for at least 10 seconds until you hear the second beep."
    )


def get_enrollment_success_text(speaker_name: str) -> str:
    return (
        f"Perfect! Your voice has been registered successfully, {speaker_name}. "
        f"I'll recognize you from now on in meetings."
    )


def get_enrollment_failure_text(speaker_name: str) -> str:
    return f"Sorry {speaker_name}, the registration didn't work. Please try again."
