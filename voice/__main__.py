"""Entry point: python -m voice"""

import logging
import argparse

from voice.config import VoiceConfig
from voice.client import VoicePickingClient


def main():
    parser = argparse.ArgumentParser(description="Voice Picking Client")
    parser.add_argument("--mode", choices=["simple", "verified"], default=None,
                        help="Picking mode: simple (MVP) or verified (with location/barcode checks)")
    parser.add_argument("--list-devices", action="store_true",
                        help="List available audio devices and exit")
    args = parser.parse_args()

    if args.list_devices:
        from voice import audio
        audio.list_devices()
        return

    config = VoiceConfig.from_env()

    # CLI arg overrides env var
    if args.mode:
        config.mode = args.mode

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    client = VoicePickingClient(config)
    client.start()


if __name__ == "__main__":
    main()
