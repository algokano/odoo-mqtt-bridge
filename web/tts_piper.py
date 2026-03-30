"""Text-to-Speech using Piper TTS (local, offline).

Generates WAV audio bytes that can be sent to the browser over WebSocket.
Replaces the macOS-only `say` command used in voice/tts.py.
"""

import io
import logging
import struct
import subprocess

import numpy as np

logger = logging.getLogger(__name__)

_voice = None  # piper.PiperVoice instance
_use_subprocess = False
_model_path = ""


def load_model(model_path: str):
    """Load a Piper TTS voice model.

    Args:
        model_path: Path to the .onnx model file.
                    Expects a matching .json config file alongside it.
    """
    global _voice, _use_subprocess, _model_path
    _model_path = model_path

    try:
        from piper import PiperVoice

        _voice = PiperVoice.load(model_path)
        _use_subprocess = False
        logger.info("Piper TTS loaded via Python API: %s", model_path)
    except (ImportError, Exception) as e:
        logger.warning("Piper Python API unavailable (%s), falling back to subprocess", e)
        _use_subprocess = True
        # Verify piper binary exists
        try:
            subprocess.run(["piper", "--version"], capture_output=True, check=True)
            logger.info("Piper TTS will use subprocess: %s", model_path)
        except FileNotFoundError:
            raise RuntimeError(
                "Piper TTS not available. Install via: pip install piper-tts\n"
                "Or download the binary from: https://github.com/rhasspy/piper/releases"
            )


def _numpy_to_wav(audio: np.ndarray, sample_rate: int = 22050) -> bytes:
    """Convert numpy int16 array to WAV bytes."""
    buf = io.BytesIO()
    num_samples = len(audio)
    data_size = num_samples * 2  # 16-bit = 2 bytes per sample

    # WAV header
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))       # chunk size
    buf.write(struct.pack("<H", 1))        # PCM format
    buf.write(struct.pack("<H", 1))        # mono
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", sample_rate * 2))  # byte rate
    buf.write(struct.pack("<H", 2))        # block align
    buf.write(struct.pack("<H", 16))       # bits per sample
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(audio.tobytes())

    return buf.getvalue()


def synthesize(text: str) -> bytes:
    """Convert text to WAV audio bytes.

    Args:
        text: Text to synthesize.

    Returns:
        WAV file bytes (PCM 16-bit mono).
    """
    if not text.strip():
        return b""

    if _use_subprocess:
        return _synthesize_subprocess(text)
    return _synthesize_python(text)


def _synthesize_python(text: str) -> bytes:
    """Synthesize using Piper Python API."""
    import wave

    if _voice is None:
        raise RuntimeError("Piper model not loaded. Call load_model() first.")

    wav_io = io.BytesIO()
    wav_file = wave.open(wav_io, "wb")
    _voice.synthesize_wav(text, wav_file)
    wav_file.close()
    return wav_io.getvalue()


def _synthesize_subprocess(text: str) -> bytes:
    """Synthesize using piper command-line binary."""
    result = subprocess.run(
        [
            "piper",
            "--model", _model_path,
            "--output-raw",
        ],
        input=text.encode("utf-8"),
        capture_output=True,
    )

    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace")
        logger.error("Piper TTS failed: %s", error)
        raise RuntimeError(f"TTS synthesis failed: {error}")

    # piper --output-raw gives raw int16 PCM at the model's sample rate (typically 22050)
    audio = np.frombuffer(result.stdout, dtype=np.int16)
    return _numpy_to_wav(audio, sample_rate=22050)
