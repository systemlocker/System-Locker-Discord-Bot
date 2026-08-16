"""Entry point: python main.py [-c config.json] [--sync-global]."""

from __future__ import annotations

import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from systemlocker_bot import __version__
from systemlocker_bot.bot import run_bot
from systemlocker_bot.config import ConfigError, load_config

LOG_DIRECTORY = Path("logs")


def configure_logging() -> None:
    LOG_DIRECTORY.mkdir(exist_ok=True)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))

    audit_file = RotatingFileHandler(
        LOG_DIRECTORY / "audit.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    audit_file.setFormatter(logging.Formatter("%(asctime)s %(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(console)

    audit = logging.getLogger("systemlocker_bot.audit")
    audit.setLevel(logging.INFO)
    audit.propagate = False
    audit.addHandler(audit_file)

    logging.getLogger("discord").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="systemlocker-bot", description="System Locker Management API v2 Discord bot"
    )
    parser.add_argument("-c", "--config", default=None, help="path to the configuration file")
    parser.add_argument(
        "--sync-global",
        action="store_true",
        help="also register commands globally (can take up to an hour to appear)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging()
    logging.getLogger("systemlocker_bot").info("System Locker Discord bot %s starting.", __version__)

    try:
        config = load_config(args.config)
    except ConfigError as error:
        logging.getLogger("systemlocker_bot").error("%s", error)
        return 2

    try:
        asyncio.run(run_bot(config, sync_global=args.sync_global))
    except KeyboardInterrupt:
        logging.getLogger("systemlocker_bot").info("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
