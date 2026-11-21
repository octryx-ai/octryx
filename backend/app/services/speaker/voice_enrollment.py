"""Voice-based speaker enrollment via Teams call.

Allows users to register their voice by saying:
  "Hey Worker, register my voice as <Name>"

The bot then:
1. Responds with instructions + beep
2. Records ~15 seconds of the user talking
3. Extracts a voice embedding
4. Enrolls the speaker
5. Confirms with TTS

This module handles the detection of enrollment commands and
manages the multi-step enrollment state machine.
"""

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

# --- Enrollment command patterns ---
# Matches: "register my voice as Alice"
# Also matches simpler forms: "register my voice" (name from caller identity)
_ENROLL_PATTERNS_WITH_NAME = [
    # English — with explicit name
    re.compile(r"register\s+(?:my\s+)?voice\s+(?:as|for)\s+(.+)", re.IGNORECASE),
    re.compile(r"enroll\s+(?:my\s+)?voice\s+(?:as|for)\s+(.+)", re.IGNORECASE),
    re.compile(r"save\s+(?:my\s+)?voice\s+(?:as|for)\s+(.+)", re.IGNORECASE),
    re.compile(r"record\s+(?:my\s+)?voice\s+(?:as|for)\s+(.+)", re.IGNORECASE),
]

# Simpler patterns that don't require a name (name comes from Teams caller identity)
_ENROLL_PATTERNS_NO_NAME = [
    # English
    re.compile(r"register\s+(?:my\s+)?voice", re.IGNORECASE),
    re.compile(r"enroll\s+(?:my\s+)?voice", re.IGNORECASE),
    re.compile(r"save\s+(?:my\s+)?voice", re.IGNORECASE),
    re.compile(r"record\s+(?:my\s+)?voice", re.IGNORECASE),
]

# Fuzzy keywords: if multiple of these appear in the text, it's likely an enrollment command
# Catches common Whisper mis-transcriptions like "rest of my voice" for "register my voice"
_ENROLL_FUZZY_KEYWORDS = [
    "register",
    "voice",
    "enroll",
    "save",
    # Common whisper garbles:
    "rest",
    "my voice",
]


class EnrollmentState(Enum):
    """State machine for the enrollment flow."""

    IDLE = auto()
    AWAITING_SAMPLE = auto()  # Waiting for the user to speak after beep


@dataclass
class EnrollmentSession:
    """Active enrollment session for a call."""

    speaker_name: str
    project_id: str
    state: EnrollmentState = EnrollmentState.AWAITING_SAMPLE
    call_id: str = ""


# Active enrollment sessions (call_id -> session)
_enrollment_sessions: dict[str, EnrollmentSession] = {}


def detect_enrollment_command(command_text: str, caller_display_name: str = "") -> str | None:
    """Check if the command text is a voice enrollment request.

    Args:
        command_text: The text after the wake word (or full text in direct calls)
        caller_display_name: The caller's display name from Teams (used if no explicit name given)

    Returns:
        The speaker name to enroll, or None if not an enrollment command.
    """
    text = command_text.strip()

    # First try patterns WITH an explicit name ("register my voice as Alice")
    for pattern in _ENROLL_PATTERNS_WITH_NAME:
        match = pattern.search(text)
        if match:
            name = match.group(1).strip().rstrip(".!?,;:")
            # Clean up common filler words
            name = re.sub(r"\bplease\b", "", name, flags=re.IGNORECASE).strip()
            if name and len(name) < 50:
                return name

    # Then try patterns WITHOUT a name — use caller identity from Teams
    for pattern in _ENROLL_PATTERNS_NO_NAME:
        if pattern.search(text):
            if caller_display_name and caller_display_name.strip():
                # Use full display name from Teams (e.g., "Alice Example")
                return caller_display_name.strip()
            # If no caller name available, return a placeholder — the flow will ask for the name
            return _UNKNOWN_CALLER_PLACEHOLDER

    # Fuzzy fallback: Whisper often garbles "register my voice" into
    # "rest of my voice", "have a good rest of my voice", etc.
    # Check if text contains "voice" AND a keyword related to registration.
    text_lower = text.lower()
    has_voice = "voice" in text_lower
    has_register_keyword = any(
        kw in text_lower for kw in ("register", "regist", "enroll", "save", "record", "rest")
    )
    if has_voice and has_register_keyword:
        if caller_display_name and caller_display_name.strip():
            logger.info("Fuzzy enrollment match: chars=%d → name=%s", len(text), person_log_ref(caller_display_name))
            return caller_display_name.strip()
        # No caller name → use placeholder
        return _UNKNOWN_CALLER_PLACEHOLDER

    return None


def start_enrollment(call_id: str, speaker_name: str, project_id: str) -> EnrollmentSession:
    """Start a voice enrollment session for a call."""
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
    """Get the active enrollment session for a call, if any."""
    return _enrollment_sessions.get(call_id)


def complete_enrollment(call_id: str) -> EnrollmentSession | None:
    """Remove and return the enrollment session (completed or cancelled)."""
    return _enrollment_sessions.pop(call_id, None)


def generate_beep(
    frequency: float = 880.0,
    duration_sec: float = 0.5,
    sample_rate: int = 16000,
    volume: float = 0.6,
) -> bytes:
    """Generate a beep tone as WAV bytes.

    Args:
        frequency: Tone frequency in Hz (880 = A5, a pleasant beep)
        duration_sec: Duration of the beep in seconds
        sample_rate: Sample rate (16kHz for Teams audio)
        volume: Volume (0.0 - 1.0)

    Returns:
        WAV bytes of the beep tone
    """
    n_samples = int(sample_rate * duration_sec)
    samples = []

    for i in range(n_samples):
        t = i / sample_rate
        # Sine wave with a slight fade-in/out to avoid clicks
        fade_samples = int(sample_rate * 0.02)  # 20ms fade
        amplitude = volume
        if i < fade_samples:
            amplitude *= i / fade_samples
        elif i > n_samples - fade_samples:
            amplitude *= (n_samples - i) / fade_samples

        sample = amplitude * math.sin(2 * math.pi * frequency * t)
        samples.append(int(sample * 32767))

    # Pack as WAV
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    return buf.getvalue()


def get_enrollment_instruction_text(speaker_name: str) -> str:
    """Get the TTS instruction text for the enrollment flow."""
    return (
        f"Okay {speaker_name}, I'll register your voice now. "
        f"Please talk freely after the beep. "
        f"Keep talking for at least 10 seconds until you hear the second beep."
    )


def get_enrollment_success_text(speaker_name: str) -> str:
    """Get the TTS confirmation text after successful enrollment."""
    return (
        f"Perfect! Your voice has been registered successfully, {speaker_name}. "
        f"I'll recognize you from now on in meetings."
    )


def get_enrollment_failure_text(speaker_name: str) -> str:
    """Get the TTS error text if enrollment fails."""
    return f"Sorry {speaker_name}, the registration didn't work. Please try again."
