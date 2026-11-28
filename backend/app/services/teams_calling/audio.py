"""PCM audio helpers for Teams Calling."""

from __future__ import annotations

import io
import struct
import wave
from dataclasses import dataclass


@dataclass(frozen=True)
class PcmAudioFormat:
    sample_rate: int = 16_000
    channels: int = 1
    sample_width: int = 2

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.channels * self.sample_width

    def duration_ms(self, pcm: bytes) -> int:
        if not pcm:
            return 0
        return int(len(pcm) * 1000 / self.bytes_per_second)


DEFAULT_PCM_FORMAT = PcmAudioFormat()


def pcm_to_wav(pcm: bytes, audio_format: PcmAudioFormat = DEFAULT_PCM_FORMAT) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(audio_format.channels)
        wav_file.setsampwidth(audio_format.sample_width)
        wav_file.setframerate(audio_format.sample_rate)
        wav_file.writeframes(pcm)
    return buf.getvalue()


def pcm_rms(pcm_chunk: bytes, audio_format: PcmAudioFormat = DEFAULT_PCM_FORMAT) -> float:
    sample_width = audio_format.sample_width
    if sample_width != 2:
        raise ValueError("pcm_rms currently supports 16-bit PCM only")
    sample_count = len(pcm_chunk) // sample_width
    if sample_count == 0:
        return 0.0
    samples = struct.unpack(f"<{sample_count}h", pcm_chunk[: sample_count * sample_width])
    return (sum(sample * sample for sample in samples) / sample_count) ** 0.5


@dataclass
class SpeechBuffer:
    audio_format: PcmAudioFormat = DEFAULT_PCM_FORMAT
    silence_flush_ms: int = 700
    energy_threshold: int = 200
    pcm: bytearray | None = None
    silent_bytes: int = 0

    def __post_init__(self) -> None:
        if self.pcm is None:
            self.pcm = bytearray()

    @property
    def silence_flush_bytes(self) -> int:
        return int(self.audio_format.bytes_per_second * self.silence_flush_ms / 1000)

    @property
    def has_speech(self) -> bool:
        return bool(self.pcm)

    def add_chunk(self, chunk: bytes) -> bool:
        rms = pcm_rms(chunk, self.audio_format)
        if rms < self.energy_threshold:
            self.silent_bytes += len(chunk)
            return self.has_speech and self.silent_bytes >= self.silence_flush_bytes

        self.silent_bytes = 0
        assert self.pcm is not None
        self.pcm.extend(chunk)
        return False

    def take(self) -> bytes:
        assert self.pcm is not None
        pcm = bytes(self.pcm)
        self.pcm.clear()
        self.silent_bytes = 0
        return pcm

