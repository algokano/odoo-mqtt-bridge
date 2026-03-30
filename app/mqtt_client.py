import json
import paho.mqtt.client as mqtt

from app.config import Config
from app.odoo_client import OdooClient
from app.utils.logger import setup_logger
from app.handlers import (
    handle_get_picking_list,
    handle_request_next,
    handle_confirm_item,
)

logger = setup_logger("mqtt_client")

TOPIC_PREFIX = "warehouse/picking"

ROUTES = {
    f"{TOPIC_PREFIX}/list": handle_get_picking_list,
    f"{TOPIC_PREFIX}/next": handle_request_next,
    f"{TOPIC_PREFIX}/confirm": handle_confirm_item,
}


class MqttBridge:
    def __init__(self, config: Config, odoo: OdooClient):
        self.config = config
        self.odoo = odoo
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0 or rc.value == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe(f"{TOPIC_PREFIX}/#")
            logger.info("Subscribed to %s/#", TOPIC_PREFIX)
        else:
            logger.error("MQTT connection failed with code %s", rc)

    def _on_message(self, client, userdata, msg, properties=None):
        topic = msg.topic
        handler = ROUTES.get(topic)

        if not handler:
            if not topic.endswith("/response"):
                logger.warning("No handler for topic: %s", topic)
            return

        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.publish(f"{topic}/response", {"ok": False, "error": f"Invalid payload: {e}"})
            return

        try:
            result = handler(self.odoo, payload)
            # Echo request_id so callers can correlate responses
            if "request_id" in payload:
                result["request_id"] = payload["request_id"]
            self.publish(f"{topic}/response", result)
        except Exception as e:
            logger.exception("Handler error on %s", topic)
            error_resp = {"ok": False, "error": str(e)}
            if "request_id" in payload:
                error_resp["request_id"] = payload["request_id"]
            self.publish(f"{topic}/response", error_resp)

    def publish(self, topic: str, payload: dict):
        message = json.dumps(payload, default=str)
        self.client.publish(topic, message)
        logger.debug("Published to %s: %s", topic, message[:200])

    def start(self):
        logger.info("Connecting to MQTT %s:%s", self.config.mqtt_host, self.config.mqtt_port)
        self.client.connect(self.config.mqtt_host, self.config.mqtt_port, 60)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("MQTT client disconnected")
