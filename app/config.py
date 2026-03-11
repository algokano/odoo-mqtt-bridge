import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Config:
    odoo_url: str
    odoo_db: str
    odoo_user: str
    odoo_password: str
    mqtt_host: str
    mqtt_port: int
    poll_interval: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        odoo_db = os.getenv("ODOO_DB")
        odoo_user = os.getenv("ODOO_USER")
        odoo_password = os.getenv("ODOO_PASS")

        missing = []
        if not odoo_db:
            missing.append("ODOO_DB")
        if not odoo_user:
            missing.append("ODOO_USER")
        if not odoo_password:
            missing.append("ODOO_PASS")
        if missing:
            print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
            sys.exit(1)

        return cls(
            odoo_url=os.getenv("ODOO_URL", "http://localhost:8069"),
            odoo_db=odoo_db,
            odoo_user=odoo_user,
            odoo_password=odoo_password,
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            poll_interval=int(os.getenv("POLL_INTERVAL", "10")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
