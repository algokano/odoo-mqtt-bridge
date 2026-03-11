import signal
import time
from datetime import datetime, timezone

from app.config import Config
from app.odoo_client import OdooClient
from app.mqtt_client import MqttBridge
from app.utils.logger import setup_logger

logger = setup_logger("main")

running = True


def shutdown(signum, frame):
    global running
    logger.info("Shutdown signal received")
    running = False


def poll_picking_events(odoo: OdooClient, bridge: MqttBridge, state_cache: dict, last_poll: str):
    pickings = odoo.search_read(
        "stock.picking",
        [["write_date", ">=", last_poll]],
        ["id", "name", "state", "picking_type_id"],
    )

    for p in pickings:
        pid = p["id"]
        new_state = p["state"]
        old_state = state_cache.get(pid)

        if old_state == new_state:
            continue

        state_cache[pid] = new_state

        if new_state == "assigned" and old_state != "assigned":
            bridge.publish("warehouse/event/picking_ready", {
                "picking_id": pid,
                "name": p["name"],
                "picking_type": p["picking_type_id"][1] if p.get("picking_type_id") else None,
            })
            logger.info("Event: picking_ready %s (%s)", p["name"], pid)

        elif new_state == "done":
            bridge.publish("warehouse/event/picking_done", {
                "picking_id": pid,
                "name": p["name"],
            })
            logger.info("Event: picking_done %s (%s)", p["name"], pid)

    # Clean up completed pickings from cache
    for pid in [k for k, v in state_cache.items() if v in ("done", "cancel")]:
        del state_cache[pid]

    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def main():
    global running

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    config = Config.from_env()
    logger.setLevel(config.log_level)
    logger.info("Starting MQTT-Odoo bridge")

    odoo = OdooClient(config)
    odoo.login()

    bridge = MqttBridge(config, odoo)
    bridge.start()

    state_cache = {}
    last_poll = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    logger.info("Bridge running. Polling every %ss. Press Ctrl+C to stop.", config.poll_interval)

    while running:
        try:
            last_poll = poll_picking_events(odoo, bridge, state_cache, last_poll)
        except Exception:
            logger.exception("Polling error")
        time.sleep(config.poll_interval)

    bridge.stop()
    logger.info("Bridge stopped")


if __name__ == "__main__":
    main()
