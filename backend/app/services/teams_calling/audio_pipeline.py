"""Audio pipeline helpers for Teams calls: TTS output and recording control."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...services.tts import get_tts_provider
from .audio import DEFAULT_PCM_FORMAT

logger = logging.getLogger(__name__)

SILENCE_FLUSH_MS = 700
ENERGY_THRESHOLD = 200  # RMS below this = silence
MAX_AUDIO_CHUNK_BYTES = DEFAULT_PCM_FORMAT.bytes_per_second * 5


def estimate_wav_duration(audio_bytes: bytes) -> float:
    # WAV header is 44 bytes; data size = total - 44
    if len(audio_bytes) < 44:
        return 2.0
    try:
        import struct

        # Canonical WAV header offsets: 24 sample rate, 34 bits per sample, 22 channels (little-endian).
        sample_rate = struct.unpack_from("<I", audio_bytes, 24)[0]
        bits_per_sample = struct.unpack_from("<H", audio_bytes, 34)[0]
        num_channels = struct.unpack_from("<H", audio_bytes, 22)[0]
        data_size = len(audio_bytes) - 44
        bytes_per_second = sample_rate * num_channels * (bits_per_sample // 8)
        if bytes_per_second > 0:
            return data_size / bytes_per_second
    except Exception:
        pass
    # Fallback: assume 16kHz mono 16-bit
    data_size = len(audio_bytes) - 44
    return max(2.0, data_size / 32000.0)


async def tts_to_pcm(text: str, db: AsyncSession, project_id: str | None = None) -> bytes | None:
    provider = await get_tts_provider(db, project_id=project_id)
    if provider is None:
        return None
    # MP3/WAV pass through as-is: the MediaBridge decodes them to PCM before injecting into the call.
    return await provider.synthesize(text, voice="alloy", speed=1.0)


async def restart_recording(call_id: str, channel_id: str) -> None:
    from ...plugins import plugin_manager

    plugin = plugin_manager.get_channel(channel_id)
    if plugin and hasattr(plugin, "_start_record"):
        await plugin._start_record(call_id)
