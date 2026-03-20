#!/usr/bin/env python3
"""
Interactive test script for voice picking — uses keyboard input instead of mic.
This lets you test the full MQTT flow without needing faster-whisper or a microphone.

Usage:
    .venv/bin/python -m voice.test_flow
    .venv/bin/python -m voice.test_flow --mode verified
"""

import json
import logging
import threading
import time
import subprocess
import argparse

import paho.mqtt.client as mqtt

from voice.config import VoiceConfig
from voice.state_machine import State, PickingContext, compute_check_digit, get_barcode_suffix
from voice.commands import parse_intent, IntentType
from voice import prompts

# MQTT topics
TOPIC_NEXT = "warehouse/picking/next"
TOPIC_NEXT_RESPONSE = "warehouse/picking/next/response"
TOPIC_CONFIRM = "warehouse/picking/confirm"
TOPIC_CONFIRM_RESPONSE = "warehouse/picking/confirm/response"
TOPIC_EVENT_READY = "warehouse/event/picking_ready"
TOPIC_EVENT_DONE = "warehouse/event/picking_done"

RESPONSE_TIMEOUT = 10.0


class TextVoiceClient:
    """Voice client that uses typed text instead of microphone — for testing."""

    def __init__(self, config: VoiceConfig):
        self.config = config
        self.state = State.IDLE
        self.ctx = PickingContext()
        self.running = False

        self._response_data = None
        self._response_event = threading.Event()
        self._last_announcement = ""
        self._current_check_digit = 0
        self._current_barcode_suffix = ""

        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        rc_val = rc if isinstance(rc, int) else rc.value
        if rc_val == 0:
            print("  [MQTT] Connected to broker")
            client.subscribe(TOPIC_NEXT_RESPONSE)
            client.subscribe(TOPIC_CONFIRM_RESPONSE)
            client.subscribe(TOPIC_EVENT_READY)
            client.subscribe(TOPIC_EVENT_DONE)
        else:
            print(f"  [MQTT] Connection failed: {rc}")

    def _on_message(self, client, userdata, msg, properties=None):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        if msg.topic in (TOPIC_NEXT_RESPONSE, TOPIC_CONFIRM_RESPONSE):
            self._response_data = data
            self._response_event.set()
        elif msg.topic == TOPIC_EVENT_READY:
            name = data.get("name", "unknown")
            if self.state == State.IDLE:
                self._say(f"New picking available: {name}. Say next item to start.")
        elif msg.topic == TOPIC_EVENT_DONE:
            name = data.get("name", "unknown")
            print(f"  [EVENT] Picking done: {name}")

    def _publish(self, topic, payload):
        message = json.dumps(payload, default=str)
        self.mqtt_client.publish(topic, message)
        print(f"  [MQTT] Published to {topic}")

    def _wait_response(self, timeout=RESPONSE_TIMEOUT):
        self._response_event.clear()
        self._response_data = None
        if self._response_event.wait(timeout):
            return self._response_data
        return None

    def _say(self, text):
        self._last_announcement = text
        print(f"\n  🔊 SYSTEM: {text}\n")
        try:
            subprocess.run(
                ["say", "-v", self.config.tts_voice, "-r", str(self.config.tts_rate), text],
                check=True,
            )
        except FileNotFoundError:
            pass  # say not available (non-macOS)

    def _handle_idle(self, intent):
        if intent.type == IntentType.NEXT_ITEM:
            self._fetch_next_picking()
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
            self.running = False
        elif intent.type == IntentType.REPEAT and self._last_announcement:
            self._say(self._last_announcement)
        else:
            self._say("Say next item to begin, or stop to quit.")

    def _fetch_next_picking(self):
        self.state = State.FETCHING_PICKING
        print("  [STATE] FETCHING_PICKING")
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

        # Print raw picking data for debug
        print(f"  [DATA] Picking: {picking['name']}, {len(picking.get('lines', []))} lines")
        for i, line in enumerate(picking.get("lines", [])):
            print(f"         Line {i+1}: {line['product']} | qty={line['qty_demand']} | "
                  f"loc={line['location']} | picked={line['picked']} | "
                  f"barcode={line.get('barcode', 'N/A')}")

        self.ctx.load_picking(picking)
        self._announce_current_line()

    def _announce_current_line(self):
        line = self.ctx.current_line()
        if not line:
            self._complete_picking()
            return

        self.state = State.ANNOUNCING_LINE
        print(f"  [STATE] ANNOUNCING_LINE (line {self.ctx.current_line_index + 1}/{self.ctx.total_lines()})")

        if self.ctx.current_line_index == 0:
            self._say(prompts.announce_picking(
                self.ctx.picking_name, self.ctx.partner,
                self.ctx.current_line_index, self.ctx.total_lines(),
            ))

        if self.config.mode == "verified":
            self._start_verification(line)
        else:
            self._announce_line_simple(line)

    def _announce_line_simple(self, line):
        self._say(prompts.announce_line_simple(
            line.get("product", "unknown"),
            line.get("qty_demand", 0),
            line.get("uom", "units"),
            line.get("location", "unknown"),
        ))
        self.state = State.AWAITING_CONFIRM
        print(f"  [STATE] AWAITING_CONFIRM")

    def _handle_awaiting_confirm(self, intent):
        if intent.type == IntentType.CONFIRM:
            line = self.ctx.current_line()
            if not line:
                self.state = State.IDLE
                return
            qty = intent.value if intent.value is not None else line.get("qty_demand", 0)
            self._confirm_line(line["move_line_id"], qty)
        elif intent.type == IntentType.REPEAT and self._last_announcement:
            self._say(self._last_announcement)
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
            self.running = False
        else:
            line = self.ctx.current_line()
            qty = line.get("qty_demand", 0) if line else 0
            self._say(f"Say confirm {int(qty)} to confirm, or repeat to hear again.")

    def _confirm_line(self, move_line_id, qty):
        self.state = State.CONFIRMING
        print(f"  [STATE] CONFIRMING (move_line_id={move_line_id}, qty={qty})")
        self._publish(TOPIC_CONFIRM, {"move_line_id": move_line_id, "qty_done": qty})

        response = self._wait_response()
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
        print(f"  [STATE] PICKING_DONE")
        self._say(prompts.picking_complete(self.ctx.picking_name))
        self.ctx.clear()
        self.state = State.IDLE
        print(f"  [STATE] IDLE")

    # --- Verification mode ---

    def _start_verification(self, line):
        location = line.get("location", "unknown")
        self._current_check_digit = compute_check_digit(location)
        self._say(prompts.announce_location(location, self._current_check_digit))
        self.state = State.AWAIT_CHECK_DIGIT
        print(f"  [STATE] AWAIT_CHECK_DIGIT (expected: {self._current_check_digit})")

    def _handle_check_digit(self, intent):
        if intent.type in (IntentType.NUMBER, IntentType.CONFIRM):
            if intent.value is not None and int(intent.value) == self._current_check_digit:
                self._say(prompts.check_digit_correct())
                self._verify_product()
            else:
                self._say(prompts.check_digit_wrong())
        elif intent.type == IntentType.REPEAT and self._last_announcement:
            self._say(self._last_announcement)
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
            self.running = False
        else:
            self._say("Please say the check digit.")

    def _verify_product(self):
        line = self.ctx.current_line()
        if not line:
            self._complete_picking()
            return
        barcode = line.get("barcode")
        suffix = get_barcode_suffix(barcode) if barcode else None
        product = line.get("product", "unknown")

        if suffix:
            self._current_barcode_suffix = suffix
            self._say(prompts.announce_product(product, suffix))
            self.state = State.AWAIT_BARCODE_CONFIRM
            print(f"  [STATE] AWAIT_BARCODE_CONFIRM (expected: {suffix})")
        else:
            self._say(f"Pick {product}. No barcode available, skipping verification.")
            self._verify_quantity()

    def _handle_barcode_confirm(self, intent):
        if intent.type in (IntentType.NUMBER, IntentType.CONFIRM):
            spoken = str(int(intent.value)) if intent.value is not None else ""
            if spoken == self._current_barcode_suffix:
                self._say(prompts.barcode_correct())
                self._verify_quantity()
            else:
                self._say(prompts.barcode_wrong())
        elif intent.type == IntentType.REPEAT and self._last_announcement:
            self._say(self._last_announcement)
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
            self.running = False
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
        print(f"  [STATE] AWAIT_QTY_CONFIRM (expected: {qty})")

    def _handle_qty_confirm(self, intent):
        if intent.type in (IntentType.NUMBER, IntentType.CONFIRM):
            line = self.ctx.current_line()
            if not line:
                self.state = State.IDLE
                return
            qty = intent.value if intent.value is not None else line.get("qty_demand", 0)
            self._confirm_line(line["move_line_id"], qty)
        elif intent.type == IntentType.REPEAT and self._last_announcement:
            self._say(self._last_announcement)
        elif intent.type == IntentType.STOP:
            self._say(prompts.goodbye())
            self.running = False
        else:
            self._say("Please say the quantity to pick.")

    def _dispatch(self, intent):
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
            self.state = State.IDLE

    def start(self):
        print(f"\n{'='*60}")
        print(f"  Voice Picking Test Client (TEXT MODE)")
        print(f"  Mode: {self.config.mode}")
        print(f"  MQTT: {self.config.mqtt_host}:{self.config.mqtt_port}")
        print(f"  Device: {self.config.device_id}")
        print(f"")
        print(f"  Type commands instead of speaking:")
        print(f"    next item    — request next picking")
        print(f"    confirm 40   — confirm quantity")
        print(f"    repeat       — repeat last announcement")
        print(f"    stop         — exit")
        print(f"")
        print(f"  Verified mode also accepts:")
        print(f"    47           — check digit response")
        print(f"    3457         — barcode suffix response")
        print(f"{'='*60}\n")

        self.mqtt_client.connect(self.config.mqtt_host, self.config.mqtt_port, 60)
        self.mqtt_client.loop_start()
        time.sleep(1)

        self.running = True
        self._say(prompts.welcome())

        try:
            while self.running:
                try:
                    text = input(f"  [{self.state.name}] You > ").strip()
                    if not text:
                        continue
                    intent = parse_intent(text)
                    print(f"  [INTENT] {intent.type.name}" + (f" value={intent.value}" if intent.value else ""))
                    self._dispatch(intent)
                except (KeyboardInterrupt, EOFError):
                    break
        finally:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            print("\n  Client stopped.")


def main():
    parser = argparse.ArgumentParser(description="Voice Picking Test Client (text mode)")
    parser.add_argument("--mode", choices=["simple", "verified"], default=None)
    args = parser.parse_args()

    config = VoiceConfig.from_env()
    if args.mode:
        config.mode = args.mode

    logging.basicConfig(level=logging.WARNING)
    client = TextVoiceClient(config)
    client.start()


if __name__ == "__main__":
    main()
