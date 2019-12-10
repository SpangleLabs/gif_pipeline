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
            logging.info(f"Initialising channel: {channel.handle}")
            channel.create_directory()
            channel.initialise_videos(self.client)
        logging.info("Initialised channels")

    def initialise_helpers(self):
        helpers = [
            DuplicateHelper(),
            TelegramGifHelper()
        ]
        for helper in helpers:
            self.helpers[helper.name] = helper

    def initialise_duplicate_detector(self):
        pass

    def initialise_gif_creator(self):
        pass

    def watch_workshop(self):
        pass


if __name__ == "__main__":
    with open("config.json", "r") as c:
        conf = json.load(c)
    pipeline = Pipeline(conf)
    pipeline.initialise_channels()
    pipeline.initialise_helpers()
    pipeline.watch_workshop()
