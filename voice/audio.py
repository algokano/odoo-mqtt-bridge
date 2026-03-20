"""Microphone audio capture using sounddevice."""

import numpy as np
import sounddevice as sd
import logging

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # 16kHz — required by Whisper models
CHANNELS = 1


def record(duration: float = 3.0, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Record audio from the default microphone.

    Args:
        duration: Recording duration in seconds.
        sample_rate: Sample rate in Hz (16000 for Whisper).

    Returns:
        numpy array of float32 audio samples, shape (n_samples,).
    """
    logger.info(f"Recording {duration}s of audio...")
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=CHANNELS,
        dtype="float32",
    )
    sd.wait()  # block until recording is done
    logger.info("Recording complete.")
    return audio.flatten()


def list_devices():
    """Print available audio devices."""
    print(sd.query_devices())


def get_default_input_device():
    """Return info about the default input device."""
    return sd.query_devices(kind="input")
