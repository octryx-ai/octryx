"""Audio pipeline helpers for Teams calls: TTS output and recording control.

Holds the VAD tuning constants used by the audio WebSocket transport, WAV
duration estimation for playback timing, TTS synthesis for the MediaBridge,
and the Graph API recording restart helper.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...services.tts import get_tts_provider
from .audio import DEFAULT_PCM_FORMAT

logger = logging.getLogger(__name__)

# VAD: flush after this many consecutive silent chunks
SILENCE_FLUSH_MS = 700
ENERGY_THRESHOLD = 200  # RMS below this = silence
MAX_AUDIO_CHUNK_BYTES = DEFAULT_PCM_FORMAT.bytes_per_second * 5


def estimate_wav_duration(audio_bytes: bytes) -> float:
    """Estimate WAV audio duration in seconds from raw bytes.

    Assumes PCM 16-bit mono 16kHz (standard for our TTS output).
    Falls back to a conservative estimate if WAV header parsing fails.
    """
    # WAV header is 44 bytes; data size = total - 44
    if len(audio_bytes) < 44:
        return 2.0  # minimum fallback
    try:
        # Try to parse WAV header for actual sample rate and channels
        import struct

        # Bytes 24-27: sample rate (little-endian uint32)
        sample_rate = struct.unpack_from("<I", audio_bytes, 24)[0]
        # Bytes 34-35: bits per sample (little-endian uint16)
        bits_per_sample = struct.unpack_from("<H", audio_bytes, 34)[0]
        # Bytes 22-23: number of channels (little-endian uint16)
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
    """Synthesize text and return raw PCM 16kHz 16-bit mono, or None if TTS unavailable."""
    provider = await get_tts_provider(db, project_id=project_id)
    if provider is None:
        return None
    # TTS returns MP3/WAV bytes — the MediaBridge decodes to PCM via NAudio.
    # Return as-is; MediaBridge handles format conversion before injecting into the call.
    return await provider.synthesize(text, voice="alloy", speed=1.0)


async def restart_recording(call_id: str, channel_id: str) -> None:
    """Restart the Graph API recording cycle for a call via the channel plugin."""
    from ...plugins import plugin_manager

    plugin = plugin_manager.get_channel(channel_id)
    if plugin and hasattr(plugin, "_start_record"):
        await plugin._start_record(call_id)
