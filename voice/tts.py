"""Text-to-Speech wrapper using macOS `say` command."""

import subprocess
import logging

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "Samantha"
DEFAULT_RATE = 180  # words per minute


def speak(text: str, voice: str = DEFAULT_VOICE, rate: int = DEFAULT_RATE, wait: bool = True):
    """Speak text using macOS `say` command.

    Args:
        text: Text to speak.
        voice: macOS voice name (e.g. "Samantha", "Alex").
        rate: Speech rate in words per minute.
        wait: If True, block until speech finishes. If False, return immediately.
    """
    cmd = ["say", "-v", voice, "-r", str(rate), text]
    logger.debug(f"TTS: {text}")

    if wait:
        subprocess.run(cmd, check=True)
    else:
        return subprocess.Popen(cmd)


def speak_and_wait(text: str, voice: str = DEFAULT_VOICE, rate: int = DEFAULT_RATE):
    """Speak text and block until done."""
    speak(text, voice=voice, rate=rate, wait=True)


def stop():
    """Kill any running `say` process."""
    subprocess.run(["killall", "say"], capture_output=True)
