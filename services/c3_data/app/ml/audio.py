"""Audio decoding for the YAMNet pipeline (C3-03, docs §4.2 step 2).

Decodes arbitrary clip bytes (wav/mp3/mp4/...) to a 16 kHz mono float32 waveform using ffmpeg,
piped entirely in memory. YAMNet expects 16 kHz mono float32 in [-1, 1]. The waveform is clipped
to the first 30 s. Unreadable input raises ``UnreadableClipError`` (mapped to 422 ``unreadable_clip``).
"""

from __future__ import annotations

import subprocess

import numpy as np

SAMPLE_RATE = 16000
MAX_SECONDS = 30
MAX_SAMPLES = SAMPLE_RATE * MAX_SECONDS  # 480_000


class UnreadableClipError(Exception):
    """Raised when ffmpeg cannot decode the input or produces no audio."""


def decode_audio(raw_bytes: bytes) -> np.ndarray:
    """Decode ``raw_bytes`` to a 16 kHz mono float32 numpy array, clipped to 30 s.

    Raises ``UnreadableClipError`` if the input is empty, ffmpeg fails, or no audio is produced.
    """
    if not raw_bytes:
        raise UnreadableClipError("empty input")

    # -nostdin keeps ffmpeg from swallowing our stdin; f32le is raw little-endian float32.
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "f32le",
        "pipe:1",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=raw_bytes,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:  # ffmpeg not installed
        raise UnreadableClipError("ffmpeg not available") from exc

    if proc.returncode != 0 or not proc.stdout:
        detail = proc.stderr.decode("utf-8", "replace")[:200] if proc.stderr else "no output"
        raise UnreadableClipError(f"ffmpeg decode failed: {detail}")

    waveform = np.frombuffer(proc.stdout, dtype=np.float32)
    if waveform.size == 0:
        raise UnreadableClipError("decoded to zero samples")

    # Clip to the first 30 s; copy so the array owns its buffer (frombuffer is read-only).
    return np.array(waveform[:MAX_SAMPLES], dtype=np.float32)


def duration_seconds(waveform: np.ndarray) -> float:
    """Length of a 16 kHz waveform in seconds."""
    return round(len(waveform) / SAMPLE_RATE, 3)
