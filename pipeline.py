import json
import logging
from typing import Dict

from channel import Channel
from helpers import DuplicateHelper, TelegramGifHelper
from telegram_client import TelegramClient


class Pipeline:
    def __init__(self, config: Dict):
        self.channels = [Channel.from_json(x) for x in config['channels']]
        self.workshop = config['workshop_group']
        self.client = TelegramClient(config['api_id'], config['api_hash'])
        self.helpers = {}

    def initialise_channels(self):
        logging.info("Initialising channels")
        # Scrape channels
        for channel in self.channels:
            channel.initialise_channel(self.client)
        logging.info("Initialised channels")

    def initialise_helpers(self):
        logging.info("Initialising helpers")
        helpers = [
            DuplicateHelper(),
            TelegramGifHelper()
        ]
        for helper in helpers:
            self.helpers[helper.name] = helper
        logging.info(f"Initialised {len(self.helpers)} helpers")

    def initialise_duplicate_detector(self):
        pass

    def initialise_gif_creator(self):
        pass

    def watch_workshop(self):
        logging.info("Initialising workshop")
        workshop = Channel(self.workshop)
        workshop.initialise_channel(self.client)
        logging.info("Watching workshop")
        pass


def setup_logging():
    formatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler("pipeline.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


if __name__ == "__main__":
    setup_logging()
    with open("config.json", "r") as c:
        conf = json.load(c)
    pipeline = Pipeline(conf)
    pipeline.initialise_channels()
    pipeline.initialise_helpers()
    pipeline.watch_workshop()
