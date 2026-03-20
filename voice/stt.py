"""Speech-to-Text wrapper using faster-whisper."""

import logging
import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

_model: WhisperModel | None = None


def load_model(model_size: str = "base.en", device: str = "cpu", compute_type: str = "int8"):
    """Load the faster-whisper model.

    Args:
        model_size: Whisper model size (e.g. "tiny.en", "base.en", "small.en").
        device: "cpu" or "cuda".
        compute_type: Quantization type ("int8", "float16", "float32").
    """
    global _model
    logger.info(f"Loading Whisper model: {model_size} (device={device}, compute={compute_type})")
    _model = WhisperModel(model_size, device=device, compute_type=compute_type)
    logger.info("Whisper model loaded.")


def transcribe(audio: np.ndarray, language: str = "en") -> str:
    """Transcribe audio buffer to text.

    Args:
        audio: numpy float32 array of audio samples at 16kHz.
        language: Language code.

    Returns:
        Transcribed text string (lowercase, stripped).
    """
    if _model is None:
        raise RuntimeError("Whisper model not loaded. Call load_model() first.")

    segments, info = _model.transcribe(audio, language=language, beam_size=5)
    text = " ".join(segment.text for segment in segments).strip()
    logger.info(f"STT result: '{text}' (language={info.language}, prob={info.language_probability:.2f})")
    return text.lower()
