"""FastAPI server with WebSocket endpoint for web voice picking."""

import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from voice import stt
from web.session import WebSession
from web import tts_piper
from web.audio_convert import check_ffmpeg
from web.config import WebConfig

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Voice Picking Web Server")

# Shared state (initialized in startup)
config: WebConfig | None = None
stt_semaphore = asyncio.Semaphore(1)
active_sessions: dict[str, WebSession] = {}


@app.on_event("startup")
async def startup():
    global config
    config = WebConfig.from_env()

    # Check ffmpeg
    if not check_ffmpeg():
        logger.error("ffmpeg not found. Install it: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)")
        raise RuntimeError("ffmpeg is required but not found on PATH")

    # Load Whisper STT model (shared across all sessions)
    logger.info("Loading Whisper model: %s", config.whisper_model)
    await asyncio.to_thread(stt.load_model, config.whisper_model)
    logger.info("Whisper model ready")

    # Load Piper TTS model
    if config.piper_model:
        logger.info("Loading Piper TTS model: %s", config.piper_model)
        await asyncio.to_thread(tts_piper.load_model, config.piper_model)
        logger.info("Piper TTS ready")
    else:
        logger.warning("PIPER_MODEL not set — TTS will not work. Set PIPER_MODEL=/path/to/model.onnx")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session: WebSession | None = None
    session_id = str(uuid.uuid4())[:8]

    try:
        # Wait for start_session message or create default session
        session = WebSession(
            session_id=session_id,
            device_id=f"{config.device_id}-{session_id}",
            mode=config.mode,
            picking_type=config.picking_type,
            mqtt_host=config.mqtt_host,
            mqtt_port=config.mqtt_port,
            loop=asyncio.get_event_loop(),
        )
        active_sessions[session_id] = session

        # Set up event callback to push MQTT events to the WebSocket
        async def push_event(event_data: dict):
            try:
                await ws.send_text(json.dumps(event_data))
            except Exception:
                pass

        def event_callback(event_data: dict):
            asyncio.ensure_future(push_event(event_data))

        session.set_event_callback(event_callback)

        # Send welcome
        messages, wav_audio = session.get_welcome()
        for msg in messages:
            await ws.send_text(json.dumps(msg))
        if wav_audio:
            await ws.send_bytes(wav_audio)

        logger.info("Session %s: WebSocket connected", session_id)

        # Main message loop
        while True:
            data = await ws.receive()

            if data.get("type") == "websocket.disconnect":
                break

            if "bytes" in data and data["bytes"]:
                # Binary message = audio from browser
                audio_bytes = data["bytes"]
                logger.debug("Session %s: received %d bytes of audio", session_id, len(audio_bytes))

                # Process audio through the session pipeline
                messages, wav_audio = await session.process_audio(audio_bytes, stt_semaphore)

                # Send all JSON messages
                for msg in messages:
                    await ws.send_text(json.dumps(msg))

                # Send TTS audio
                if wav_audio:
                    await ws.send_bytes(wav_audio)

            elif "text" in data and data["text"]:
                # JSON control message
                try:
                    msg = json.loads(data["text"])
                    msg_type = msg.get("type", "")

                    if msg_type == "start_session":
                        # Allow reconfiguration
                        new_mode = msg.get("mode", session.mode)
                        if new_mode != session.mode:
                            session.mode = new_mode
                            logger.info("Session %s: mode changed to %s", session_id, new_mode)

                    elif msg_type == "end_session":
                        break

                except json.JSONDecodeError:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "message": "Invalid JSON message"
                    }))

    except WebSocketDisconnect:
        logger.info("Session %s: WebSocket disconnected", session_id)
    except Exception as e:
        logger.exception("Session %s: WebSocket error", session_id)
    finally:
        if session:
            session.close()
            active_sessions.pop(session_id, None)
        logger.info("Session %s: cleaned up", session_id)
