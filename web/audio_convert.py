"""Convert browser audio (WebM/Opus) to numpy array for Whisper STT."""

import logging
import subprocess

import numpy as np

logger = logging.getLogger(__name__)


def check_ffmpeg():
    """Verify ffmpeg is installed."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=True,
        )
        return True
    except FileNotFoundError:
        return False


def webm_to_numpy(data: bytes) -> np.ndarray:
    """Convert WebM/Opus audio bytes to 16kHz mono float32 numpy array.

    Args:
        data: Raw audio bytes from browser MediaRecorder (WebM/Opus format).

    Returns:
        numpy float32 array of audio samples at 16kHz, suitable for Whisper.

    Raises:
        RuntimeError: If ffmpeg conversion fails.
    """
    result = subprocess.run(
        [
            "ffmpeg",
            "-i", "pipe:0",       # read from stdin
            "-ar", "16000",       # resample to 16kHz
            "-ac", "1",           # mono
            "-f", "f32le",        # raw float32 little-endian PCM
            "-loglevel", "error",
            "pipe:1",             # write to stdout
        ],
        input=data,
        capture_output=True,
    )

    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace")
        logger.error("ffmpeg conversion failed: %s", error)
        raise RuntimeError(f"Audio conversion failed: {error}")

    audio = np.frombuffer(result.stdout, dtype=np.float32)
    logger.debug("Converted audio: %d samples (%.1fs at 16kHz)", len(audio), len(audio) / 16000)
    return audio
