"""Configuration for the voice picking client."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class VoiceConfig:
    mqtt_host: str
    mqtt_port: int
    device_id: str
    picking_type: str
    whisper_model: str
    tts_voice: str
    tts_rate: int
    record_duration: float
    log_level: str
    mode: str  # "simple" or "verified"

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        load_dotenv()
        return cls(
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            device_id=os.getenv("VOICE_DEVICE_ID", "voice-01"),
            picking_type=os.getenv("VOICE_PICKING_TYPE", "outgoing"),
            whisper_model=os.getenv("WHISPER_MODEL", "base.en"),
            tts_voice=os.getenv("TTS_VOICE", "Samantha"),
            tts_rate=int(os.getenv("TTS_RATE", "180")),
            record_duration=float(os.getenv("RECORD_DURATION", "3.0")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            mode=os.getenv("VOICE_MODE", "simple"),
        )
