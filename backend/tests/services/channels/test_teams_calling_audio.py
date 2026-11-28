import wave
from io import BytesIO

from app.services.teams_calling.audio import DEFAULT_PCM_FORMAT, SpeechBuffer, pcm_rms, pcm_to_wav


def test_pcm_to_wav_wraps_teams_audio_format():
    pcm = (1000).to_bytes(2, "little", signed=True) * 160

    wav_bytes = pcm_to_wav(pcm)

    with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getframerate() == 16_000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.readframes(160) == pcm


def test_pcm_rms_reports_silence_and_signal_energy():
    silence = b"\x00\x00" * 160
    signal = (1000).to_bytes(2, "little", signed=True) * 160

    assert pcm_rms(silence) == 0
    assert pcm_rms(signal) == 1000


def test_speech_buffer_flushes_after_configured_silence():
    speech = (1000).to_bytes(2, "little", signed=True) * 160
    silence = b"\x00\x00" * int(DEFAULT_PCM_FORMAT.sample_rate * 0.7)
    buffer = SpeechBuffer()

    assert buffer.add_chunk(speech) is False
    assert buffer.has_speech is True
    assert buffer.add_chunk(silence) is True

    assert buffer.take() == speech
    assert buffer.has_speech is False
