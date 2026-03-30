"""WebSession — mirrors voice/client.py logic for browser-based voice picking.

Each WebSocket connection creates one WebSession. The phone sends audio,
the session processes it (STT → intent → state machine → MQTT → TTS),
and returns JSON status messages + WAV audio to play.
"""

import asyncio
import json
import logging
import uuid

import paho.mqtt.client as mqtt

from voice.state_machine import State, PickingContext, compute_check_digit, get_barcode_suffix
from voice.commands import parse_intent, IntentType
from voice import stt, prompts

from web.audio_convert import webm_to_numpy
from web import tts_piper

logger = logging.getLogger(__name__)

# MQTT topics (same as voice/client.py)
TOPIC_NEXT = "warehouse/picking/next"
TOPIC_NEXT_RESPONSE = "warehouse/picking/next/response"
TOPIC_CONFIRM = "warehouse/picking/confirm"
TOPIC_CONFIRM_RESPONSE = "warehouse/picking/confirm/response"
TOPIC_EVENT_READY = "warehouse/event/picking_ready"
TOPIC_EVENT_DONE = "warehouse/event/picking_done"

RESPONSE_TIMEOUT = 10.0


class WebSession:
    """A single worker's voice picking session over WebSocket."""

    def __init__(self, session_id: str, device_id: str, mode: str,
                 picking_type: str, mqtt_host: str, mqtt_port: int,
                 loop: asyncio.AbstractEventLoop):
        self.session_id = session_id
        self.device_id = device_id
        self.mode = mode
        self.picking_type = picking_type
        self.loop = loop

        # State machine (reused from voice/)
        self.state = State.IDLE
        self.ctx = PickingContext()

        # Verification state
        self._current_check_digit = 0
        self._current_barcode_suffix = ""

        # Response buffer: collects text from _say() calls during one process_audio cycle
        self._response_texts: list[str] = []
        self._last_announcement = ""

        # MQTT response synchronisation (async)
        self._pending_request_id: str | None = None
        self._response_data: dict | None = None
        self._response_event = asyncio.Event()

        # Callback for pushing events to WebSocket
        self._event_callback = None

        # MQTT client
        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_message
        self.mqtt.connect(mqtt_host, mqtt_port, 60)
        self.mqtt.loop_start()

        logger.info("WebSession %s created (device=%s, mode=%s)", session_id, device_id, mode)

    def set_event_callback(self, callback):
        """Set a callback for pushing async events (picking_ready, etc.) to the WebSocket."""
        self._event_callback = callback

    # --- MQTT callbacks ---

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        rc_val = rc if isinstance(rc, int) else rc.value
        if rc_val == 0:
            logger.info("Session %s: MQTT connected", self.session_id)
            client.subscribe(TOPIC_NEXT_RESPONSE)
            client.subscribe(TOPIC_CONFIRM_RESPONSE)
            client.subscribe(TOPIC_EVENT_READY)
            client.subscribe(TOPIC_EVENT_DONE)
        else:
            logger.error("Session %s: MQTT connection failed: %s", self.session_id, rc)

    def _on_message(self, client, userdata, msg, properties=None):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        if msg.topic in (TOPIC_NEXT_RESPONSE, TOPIC_CONFIRM_RESPONSE):
            # Filter by request_id to avoid cross-session responses
            if self._pending_request_id and data.get("request_id") != self._pending_request_id:
                return
            self._response_data = data
            # Signal the asyncio event from the MQTT thread
            self.loop.call_soon_threadsafe(self._response_event.set)

        elif msg.topic == TOPIC_EVENT_READY:
            name = data.get("name", "unknown")
            logger.info("Session %s: picking ready event — %s", self.session_id, name)
            if self._event_callback and self.state == State.IDLE:
                self.loop.call_soon_threadsafe(
                    self._event_callback,
                    {"type": "event", "event": "picking_ready", "name": name}
                )

        elif msg.topic == TOPIC_EVENT_DONE:
            name = data.get("name", "unknown")
            logger.info("Session %s: picking done event — %s", self.session_id, name)
            if self._event_callback:
                self.loop.call_soon_threadsafe(
                    self._event_callback,
                    {"type": "event", "event": "picking_done", "name": name}
                )

    # --- MQTT publish/wait ---

    def _publish(self, topic: str, payload: dict):
        request_id = str(uuid.uuid4())
        payload["request_id"] = request_id
        self._pending_request_id = request_id
        message = json.dumps(payload, default=str)
        self.mqtt.publish(topic, message)
        logger.debug("Session %s: published to %s (request_id=%s)", self.session_id, topic, request_id)

    async def _wait_response(self, timeout: float = RESPONSE_TIMEOUT) -> dict | None:
        self._response_event.clear()
        self._response_data = None
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout)
            return self._response_data
        except asyncio.TimeoutError:
            return None

    # --- TTS helper ---

    def _say(self, text: str):
        self._last_announcement = text
        self._response_texts.append(text)

    # --- State handlers (mirrors voice/client.py) ---

    async def _handle_idle(self, intent):
        if intent.type == IntentType.NEXT_ITEM:
            await self._fetch_next_picking()
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
        elif intent.type == IntentType.REPEAT:
            if self._last_announcement:
                self._say(self._last_announcement)
            else:
                self._say(prompts.welcome())
        else:
            self._say("Say next item to begin.")

    async def _fetch_next_picking(self):
        self.state = State.FETCHING_PICKING
        self._say(prompts.waiting_for_response())

        self._publish(TOPIC_NEXT, {
            "device_id": self.device_id,
            "picking_type": self.picking_type,
        })

        response = await self._wait_response()
        if response is None:
            self._say(prompts.timeout_message())
            self.state = State.IDLE
            return

        if not response.get("ok", False):
            self._say(prompts.error_message(response.get("error", "Unknown error")))
            self.state = State.IDLE
            return

        picking = response.get("picking")
        if not picking:
            self._say(prompts.no_pickings())
            self.state = State.IDLE
            return

        self.ctx.load_picking(picking)
        self._announce_current_line()

    def _announce_current_line(self):
        line = self.ctx.current_line()
        if not line:
            self._complete_picking()
            return

        self.state = State.ANNOUNCING_LINE

        if self.ctx.current_line_index == 0:
            self._say(prompts.announce_picking(
                self.ctx.picking_name,
                self.ctx.partner,
                self.ctx.current_line_index,
                self.ctx.total_lines(),
            ))
        else:
            self._say(f"Item {self.ctx.current_line_index + 1} of {self.ctx.total_lines()}.")

        if self.mode == "verified":
            self._start_verification(line)
        else:
            self._announce_line_simple(line)

    def _announce_line_simple(self, line: dict):
        self._say(prompts.announce_line_simple(
            line.get("product", "unknown product"),
            line.get("qty_demand", 0),
            line.get("uom", "units"),
            line.get("location", "unknown"),
        ))
        self.state = State.AWAITING_CONFIRM

    async def _handle_awaiting_confirm(self, intent):
        if intent.type == IntentType.CONFIRM:
            line = self.ctx.current_line()
            if line is None:
                self._say("No current item to confirm.")
                self.state = State.IDLE
                return
            qty = intent.value
            if qty is None:
                qty = line.get("qty_demand", 0)
            await self._confirm_line(line["move_line_id"], qty)
        elif intent.type == IntentType.REPEAT:
            if self._last_announcement:
                self._say(self._last_announcement)
        elif intent.type == IntentType.NEXT_ITEM:
            self._say("Please confirm the current item first, or say confirm.")
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
        else:
            line = self.ctx.current_line()
            qty = line.get("qty_demand", 0) if line else 0
            self._say(f"Say confirm {int(qty)} to confirm, or repeat to hear again.")

    async def _confirm_line(self, move_line_id: int, qty: float):
        self.state = State.CONFIRMING
        self._publish(TOPIC_CONFIRM, {
            "move_line_id": move_line_id,
            "qty_done": qty,
        })

        response = await self._wait_response()
        if response is None:
            self._say(prompts.timeout_message())
            self.state = State.AWAITING_CONFIRM
            return

        if not response.get("ok", False):
            self._say(prompts.error_message(response.get("error", "Confirmation failed")))
            self.state = State.AWAITING_CONFIRM
            return

        line = self.ctx.current_line()
        if line:
            line["picked"] = True

        remaining = self.ctx.remaining_lines()
        self._say(prompts.confirm_success(remaining))

        if self.ctx.advance_line():
            self._announce_current_line()
        else:
            self._complete_picking()

    def _complete_picking(self):
        self.state = State.PICKING_DONE
        self._say(prompts.picking_complete(self.ctx.picking_name))
        self.ctx.clear()
        self.state = State.IDLE

    # --- Verification workflow ---

    def _start_verification(self, line: dict):
        location = line.get("location", "unknown")
        check_digit = compute_check_digit(location)
        self._current_check_digit = check_digit
        self._say(prompts.announce_location(location, check_digit))
        self.state = State.AWAIT_CHECK_DIGIT

    async def _handle_check_digit(self, intent):
        if intent.type in (IntentType.NUMBER, IntentType.CONFIRM):
            value = intent.value
            if value is not None and int(value) == self._current_check_digit:
                self._say(prompts.check_digit_correct())
                self._verify_product()
            else:
                self._say(prompts.check_digit_wrong())
        elif intent.type == IntentType.REPEAT:
            if self._last_announcement:
                self._say(self._last_announcement)
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
        else:
            self._say("Please say the check digit to confirm your location.")

    def _verify_product(self):
        line = self.ctx.current_line()
        if not line:
            self._complete_picking()
            return

        barcode = line.get("barcode")
        suffix = get_barcode_suffix(barcode)
        product = line.get("product", "unknown product")

        if suffix:
            self._current_barcode_suffix = suffix
            self._say(prompts.announce_product(product, suffix))
            self.state = State.AWAIT_BARCODE_CONFIRM
        else:
            self._say(f"Pick {product}.")
            self._verify_quantity()

    async def _handle_barcode_confirm(self, intent):
        if intent.type in (IntentType.NUMBER, IntentType.CONFIRM):
            spoken = str(int(intent.value)) if intent.value is not None else ""
            if spoken == self._current_barcode_suffix:
                self._say(prompts.barcode_correct())
                self._verify_quantity()
            else:
                self._say(prompts.barcode_wrong())
        elif intent.type == IntentType.REPEAT:
            if self._last_announcement:
                self._say(self._last_announcement)
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
        else:
            self._say("Please say the last digits of the barcode.")

    def _verify_quantity(self):
        line = self.ctx.current_line()
        if not line:
            self._complete_picking()
            return

        qty = line.get("qty_demand", 0)
        uom = line.get("uom", "units")
        self._say(prompts.announce_quantity(qty, uom))
        self.state = State.AWAIT_QTY_CONFIRM

    async def _handle_qty_confirm(self, intent):
        if intent.type in (IntentType.NUMBER, IntentType.CONFIRM):
            qty = intent.value
            line = self.ctx.current_line()
            if line is None:
                self._say("No current item.")
                self.state = State.IDLE
                return
            if qty is None:
                qty = line.get("qty_demand", 0)
            await self._confirm_line(line["move_line_id"], qty)
        elif intent.type == IntentType.REPEAT:
            if self._last_announcement:
                self._say(self._last_announcement)
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
        else:
            self._say("Please say the quantity to pick.")

    # --- Dispatch ---

    async def _dispatch(self, intent):
        handlers = {
            State.IDLE: self._handle_idle,
            State.AWAITING_CONFIRM: self._handle_awaiting_confirm,
            State.AWAIT_CHECK_DIGIT: self._handle_check_digit,
            State.AWAIT_BARCODE_CONFIRM: self._handle_barcode_confirm,
            State.AWAIT_QTY_CONFIRM: self._handle_qty_confirm,
        }
        handler = handlers.get(self.state)
        if handler:
            await handler(intent)
        else:
            logger.warning("Session %s: no handler for state %s", self.session_id, self.state)
            self.state = State.IDLE

    # --- Main entry point ---

    async def process_audio(self, audio_bytes: bytes, stt_semaphore: asyncio.Semaphore) -> tuple[list[dict], bytes]:
        """Process audio from the browser and return response messages + TTS audio.

        Args:
            audio_bytes: Raw audio bytes from MediaRecorder (WebM/Opus).
            stt_semaphore: Semaphore to serialize STT access.

        Returns:
            Tuple of (json_messages, wav_audio_bytes).
            json_messages: list of dicts to send as JSON over WebSocket.
            wav_audio_bytes: WAV audio to send as binary over WebSocket.
        """
        self._response_texts = []
        messages = []

        try:
            # Convert browser audio to numpy
            audio = webm_to_numpy(audio_bytes)

            # STT (serialized across sessions)
            async with stt_semaphore:
                text = await asyncio.to_thread(stt.transcribe, audio)

            messages.append({"type": "transcript", "text": text})

            if not text.strip():
                self._say(prompts.please_repeat())
            else:
                intent = parse_intent(text)
                logger.info("Session %s: State=%s, Intent=%s (value=%s)",
                            self.session_id, self.state.name, intent.type.name, intent.value)
                await self._dispatch(intent)

        except Exception as e:
            logger.exception("Session %s: error processing audio", self.session_id)
            self._say(prompts.error_message(str(e)))
            self.state = State.IDLE

        # Build state message
        full_text = " ".join(self._response_texts)
        messages.append({
            "type": "state",
            "state": self.state.name,
            "text": full_text,
        })

        # Generate TTS audio
        wav_audio = b""
        if full_text:
            try:
                wav_audio = await asyncio.to_thread(tts_piper.synthesize, full_text)
            except Exception as e:
                logger.error("Session %s: TTS failed: %s", self.session_id, e)
                messages.append({"type": "error", "message": f"TTS failed: {e}"})

        messages.append({"type": "listening"})
        return messages, wav_audio

    def get_welcome(self) -> tuple[list[dict], bytes]:
        """Generate welcome messages and audio for new connection."""
        text = prompts.welcome()
        self._last_announcement = text
        messages = [
            {"type": "state", "state": self.state.name, "text": text},
            {"type": "listening"},
        ]
        try:
            wav_audio = tts_piper.synthesize(text)
        except Exception as e:
            logger.error("Session %s: TTS failed on welcome: %s", self.session_id, e)
            wav_audio = b""
            messages.insert(1, {"type": "error", "message": f"TTS failed: {e}"})
        return messages, wav_audio

    def close(self):
        """Clean up MQTT connection."""
        self.mqtt.loop_stop()
        self.mqtt.disconnect()
        logger.info("Session %s closed", self.session_id)
