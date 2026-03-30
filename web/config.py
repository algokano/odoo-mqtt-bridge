"""Configuration for the web voice server."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class WebConfig:
    # Server
    host: str
    port: int
    ssl_certfile: str
    ssl_keyfile: str

    # MQTT
    mqtt_host: str
    mqtt_port: int

    # Voice
    device_id: str
    picking_type: str
    whisper_model: str
    mode: str  # "simple" or "verified"

    # Piper TTS
    piper_model: str

    log_level: str

    @classmethod
    def from_env(cls) -> "WebConfig":
        load_dotenv()
        return cls(
            host=os.getenv("WEB_HOST", "0.0.0.0"),
            port=int(os.getenv("WEB_PORT", "8443")),
            ssl_certfile=os.getenv("SSL_CERTFILE", ""),
            ssl_keyfile=os.getenv("SSL_KEYFILE", ""),
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            device_id=os.getenv("VOICE_DEVICE_ID", "web-voice"),
            picking_type=os.getenv("VOICE_PICKING_TYPE", "outgoing"),
            whisper_model=os.getenv("WHISPER_MODEL", "base.en"),
            mode=os.getenv("VOICE_MODE", "simple"),
            piper_model=os.getenv("PIPER_MODEL", ""),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
