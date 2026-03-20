"""Main voice picking client — orchestrates MQTT, STT, TTS, and state machine."""

import json
import logging
import threading
import time

import paho.mqtt.client as mqtt

from voice.config import VoiceConfig
from voice.state_machine import State, PickingContext, compute_check_digit, get_barcode_suffix
from voice.commands import parse_intent, IntentType
from voice import tts, stt, audio, prompts

logger = logging.getLogger(__name__)

# MQTT topics
TOPIC_NEXT = "warehouse/picking/next"
TOPIC_NEXT_RESPONSE = "warehouse/picking/next/response"
TOPIC_CONFIRM = "warehouse/picking/confirm"
TOPIC_CONFIRM_RESPONSE = "warehouse/picking/confirm/response"
TOPIC_EVENT_READY = "warehouse/event/picking_ready"
TOPIC_EVENT_DONE = "warehouse/event/picking_done"

RESPONSE_TIMEOUT = 10.0  # seconds


class VoicePickingClient:
    def __init__(self, config: VoiceConfig):
        self.config = config
        self.state = State.IDLE
        self.ctx = PickingContext()
        self.running = False

        # MQTT response synchronisation
        self._response_data: dict | None = None
        self._response_event = threading.Event()

        # MQTT client
        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_message

        # Last TTS message for repeat
        self._last_announcement = ""

    # --- MQTT callbacks ---

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        rc_val = rc if isinstance(rc, int) else rc.value
        if rc_val == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe(TOPIC_NEXT_RESPONSE)
            client.subscribe(TOPIC_CONFIRM_RESPONSE)
            client.subscribe(TOPIC_EVENT_READY)
            client.subscribe(TOPIC_EVENT_DONE)
            logger.info("Subscribed to response and event topics")
        else:
            logger.error("MQTT connection failed: %s", rc)

    def _on_message(self, client, userdata, msg, properties=None):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Invalid MQTT payload on %s", msg.topic)
            return

        if msg.topic in (TOPIC_NEXT_RESPONSE, TOPIC_CONFIRM_RESPONSE):
            self._response_data = data
            self._response_event.set()
        elif msg.topic == TOPIC_EVENT_READY:
            name = data.get("name", "unknown")
            logger.info("Event: picking ready — %s", name)
            if self.state == State.IDLE:
                self._say(f"New picking available: {name}. Say next item to start.")
        elif msg.topic == TOPIC_EVENT_DONE:
            name = data.get("name", "unknown")
            logger.info("Event: picking done — %s", name)

    # --- MQTT publish/wait helpers ---

    def _publish(self, topic: str, payload: dict):
        message = json.dumps(payload, default=str)
        self.mqtt.publish(topic, message)
        logger.debug("Published to %s: %s", topic, message[:200])

    def _wait_response(self, timeout: float = RESPONSE_TIMEOUT) -> dict | None:
        self._response_event.clear()
        self._response_data = None
        if self._response_event.wait(timeout):
            return self._response_data
        return None

    # --- TTS helper ---

    def _say(self, text: str):
        self._last_announcement = text
        print(f"  >> {text}")
        tts.speak(text, voice=self.config.tts_voice, rate=self.config.tts_rate)

    # --- Voice input ---

    def _listen(self) -> str:
        input("  [Press ENTER to speak, then wait...] ")
        audio_data = audio.record(duration=self.config.record_duration)
        text = stt.transcribe(audio_data)
        print(f"  << You said: \"{text}\"")
        return text

    # --- State handlers ---

    def _handle_idle(self, intent):
        if intent.type == IntentType.NEXT_ITEM:
            self._fetch_next_picking()
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
            self.running = False
        elif intent.type == IntentType.REPEAT:
            if self._last_announcement:
                self._say(self._last_announcement)
            else:
                self._say(prompts.welcome())
        else:
            self._say("Say next item to begin, or stop to quit.")

    def _fetch_next_picking(self):
        self.state = State.FETCHING_PICKING
        self._say(prompts.waiting_for_response())
        self._publish(TOPIC_NEXT, {
            "device_id": self.config.device_id,
            "picking_type": self.config.picking_type,
        })

        response = self._wait_response()
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

        # Announce the picking header for the first line
        if self.ctx.current_line_index == 0:
            self._say(prompts.announce_picking(
                self.ctx.picking_name,
                self.ctx.partner,
                self.ctx.current_line_index,
                self.ctx.total_lines(),
            ))
        else:
            self._say(f"Item {self.ctx.current_line_index + 1} of {self.ctx.total_lines()}.")

        if self.config.mode == "verified":
            self._start_verification(line)
        else:
            self._announce_line_simple(line)

    def _announce_line_simple(self, line: dict):
        """Simple mode: announce product, qty, location, then wait for confirm."""
        self._say(prompts.announce_line_simple(
            line.get("product", "unknown product"),
            line.get("qty_demand", 0),
            line.get("uom", "units"),
            line.get("location", "unknown"),
        ))
        self.state = State.AWAITING_CONFIRM

    def _handle_awaiting_confirm(self, intent):
        if intent.type == IntentType.CONFIRM:
            line = self.ctx.current_line()
            if line is None:
                self._say("No current item to confirm.")
                self.state = State.IDLE
                return
            qty = intent.value
            if qty is None:
                qty = line.get("qty_demand", 0)
            self._confirm_line(line["move_line_id"], qty)
        elif intent.type == IntentType.REPEAT:
            if self._last_announcement:
                self._say(self._last_announcement)
        elif intent.type == IntentType.NEXT_ITEM:
            self._say("Please confirm the current item first, or say confirm.")
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
            self.running = False
        else:
            line = self.ctx.current_line()
            qty = line.get("qty_demand", 0) if line else 0
            self._say(f"Say confirm {int(qty)} to confirm, or repeat to hear again.")

    def _confirm_line(self, move_line_id: int, qty: float):
        self.state = State.CONFIRMING
        self._publish(TOPIC_CONFIRM, {
            "move_line_id": move_line_id,
            "qty_done": qty,
        })

        response = self._wait_response()
        if response is None:
            self._say(prompts.timeout_message())
            self.state = State.AWAITING_CONFIRM
            return

        if not response.get("ok", False):
            self._say(prompts.error_message(response.get("error", "Confirmation failed")))
            self.state = State.AWAITING_CONFIRM
            return

        # Mark current line as picked locally
        line = self.ctx.current_line()
        if line:
            line["picked"] = True

        remaining = self.ctx.remaining_lines()
        self._say(prompts.confirm_success(remaining))

        # Move to next line or complete
        if self.ctx.advance_line():
            self._announce_current_line()
        else:
            self._complete_picking()

    def _complete_picking(self):
        self.state = State.PICKING_DONE
        self._say(prompts.picking_complete(self.ctx.picking_name))
        self.ctx.clear()
        self.state = State.IDLE

    # --- Phase 2: Verification workflow ---

    def _start_verification(self, line: dict):
        """Begin the location → product → quantity verification sequence."""
        location = line.get("location", "unknown")
        check_digit = compute_check_digit(location)
        self._current_check_digit = check_digit
        self._say(prompts.announce_location(location, check_digit))
        self.state = State.AWAIT_CHECK_DIGIT

    def _handle_check_digit(self, intent):
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
            self.running = False
        else:
            self._say(f"Please say the check digit to confirm your location.")

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
            # No barcode available, skip to quantity
            self._say(f"Pick {product}.")
            self._verify_quantity()

    def _handle_barcode_confirm(self, intent):
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
            self.running = False
        else:
            self._say(f"Please say the last digits of the barcode.")

    def _verify_quantity(self):
        line = self.ctx.current_line()
        if not line:
            self._complete_picking()
            return

        qty = line.get("qty_demand", 0)
        uom = line.get("uom", "units")
        self._say(prompts.announce_quantity(qty, uom))
        self.state = State.AWAIT_QTY_CONFIRM

    def _handle_qty_confirm(self, intent):
        if intent.type in (IntentType.NUMBER, IntentType.CONFIRM):
            qty = intent.value
            line = self.ctx.current_line()
            if line is None:
                self._say("No current item.")
                self.state = State.IDLE
                return
            if qty is None:
                qty = line.get("qty_demand", 0)
            self._confirm_line(line["move_line_id"], qty)
        elif intent.type == IntentType.REPEAT:
            if self._last_announcement:
                self._say(self._last_announcement)
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
            self.running = False
        else:
            self._say("Please say the quantity to pick.")

    # --- Main loop ---

    def _dispatch(self, intent):
        """Route intent to the appropriate state handler."""
        handlers = {
            State.IDLE: self._handle_idle,
            State.AWAITING_CONFIRM: self._handle_awaiting_confirm,
            State.AWAIT_CHECK_DIGIT: self._handle_check_digit,
            State.AWAIT_BARCODE_CONFIRM: self._handle_barcode_confirm,
            State.AWAIT_QTY_CONFIRM: self._handle_qty_confirm,
        }
        handler = handlers.get(self.state)
        if handler:
            handler(intent)
        else:
            logger.warning("No handler for state %s, returning to IDLE", self.state)
            self.state = State.IDLE

    def start(self):
        """Start the voice picking client."""
        # Load STT model
        stt.load_model(self.config.whisper_model)

        # Connect MQTT
        logger.info("Connecting to MQTT %s:%s", self.config.mqtt_host, self.config.mqtt_port)
        self.mqtt.connect(self.config.mqtt_host, self.config.mqtt_port, 60)
        self.mqtt.loop_start()

        # Wait for connection
        time.sleep(1)

        self.running = True
        mode_label = "verified" if self.config.mode == "verified" else "simple"
        print(f"\n{'='*50}")
        print(f"  Voice Picking Client — {mode_label} mode")
        print(f"  Device: {self.config.device_id}")
        print(f"  MQTT: {self.config.mqtt_host}:{self.config.mqtt_port}")
        print(f"{'='*50}\n")

        self._say(prompts.welcome())

        try:
            while self.running:
                try:
                    text = self._listen()
                    if not text.strip():
                        self._say(prompts.please_repeat())
                        continue

                    intent = parse_intent(text)
                    logger.info("State=%s, Intent=%s (value=%s)", self.state.name, intent.type.name, intent.value)
                    self._dispatch(intent)

                except KeyboardInterrupt:
                    break
                except Exception as e:
                    logger.exception("Error in main loop")
                    self._say(prompts.error_message(str(e)))
                    self.state = State.IDLE
        finally:
            self.stop()

    def stop(self):
        """Stop the client and clean up."""
        self.running = False
        self.mqtt.loop_stop()
        self.mqtt.disconnect()
        logger.info("Voice picking client stopped")
