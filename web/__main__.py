"""Entry point for the web voice server: python -m web"""

import logging
import uvicorn

from web.config import WebConfig


def main():
    config = WebConfig.from_env()

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    ssl_kwargs = {}
    if config.ssl_certfile and config.ssl_keyfile:
        ssl_kwargs["ssl_certfile"] = config.ssl_certfile
        ssl_kwargs["ssl_keyfile"] = config.ssl_keyfile

    print(f"\n{'='*50}")
    print(f"  Web Voice Picking Server")
    print(f"  Host: {config.host}:{config.port}")
    if ssl_kwargs:
        print(f"  HTTPS: enabled")
        print(f"  URL: https://{config.host}:{config.port}")
    else:
        print(f"  HTTP: enabled (microphone only works on localhost)")
        print(f"  URL: http://localhost:{config.port}")
    print(f"  MQTT: {config.mqtt_host}:{config.mqtt_port}")
    print(f"  Mode: {config.mode}")
    print(f"{'='*50}\n")

    uvicorn.run(
        "web.server:app",
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
