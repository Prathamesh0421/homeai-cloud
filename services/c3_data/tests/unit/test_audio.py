"""C3-03: ffmpeg audio decode to 16 kHz mono float32, 30 s clipping, error handling.

These tests shell out to ffmpeg; they are skipped automatically when ffmpeg is not installed.
"""

from __future__ import annotations

import math
import shutil
import struct
import wave

import numpy as np
import pytest
from app.ml.audio import MAX_SAMPLES, SAMPLE_RATE, UnreadableClipError, decode_audio

ffmpeg_required = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _wav_bytes(seconds: float, rate: int = 44100, freq: float = 440.0) -> bytes:
    """A mono 16-bit PCM sine wave WAV in memory (rate != 16k on purpose, to test resample)."""
    import io

    n = int(rate * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(0.5 * 32767 * math.sin(2 * math.pi * freq * i / rate)))
            for i in range(n)
        )
        w.writeframes(frames)
    return buf.getvalue()


@ffmpeg_required
def test_decode_wav_to_16k_mono_float32():
    wav = _wav_bytes(1.0)
    out = decode_audio(wav)
    assert out.dtype == np.float32
    assert out.ndim == 1
    # ~1 s at 16 kHz (allow a few samples of resampler slack).
    assert abs(len(out) - SAMPLE_RATE) < 200


@ffmpeg_required
def test_decode_clips_to_30_seconds():
    wav = _wav_bytes(32.0, rate=16000)  # 32 s source
    out = decode_audio(wav)
    assert len(out) == MAX_SAMPLES  # 480_000


@ffmpeg_required
def test_garbage_bytes_raise_unreadable():
    with pytest.raises(UnreadableClipError):
        decode_audio(b"this is not audio at all" * 100)


def test_empty_input_raises_unreadable():
    with pytest.raises(UnreadableClipError):
        decode_audio(b"")
