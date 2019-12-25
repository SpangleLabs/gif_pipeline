import json
import logging
from typing import Dict

from channel import Channel, WorkshopGroup
from helpers import DuplicateHelper, TelegramGifHelper
from telegram_client import TelegramClient


class Pipeline:
    def __init__(self, config: Dict):
        self.channels = [Channel.from_json(x) for x in config['channels']]
        self.workshop_handle = config['workshop_group']
        self.workshop = WorkshopGroup(self.workshop_handle)
        self.client = TelegramClient(config['api_id'], config['api_hash'])
        self.helpers = {}

    @property
    def all_channels(self) -> List[Group]:
        channels = [x for x in self.channels]  # type: List[Group]
        channels.append(self.workshop)
        return channels

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
        self.workshop.initialise_channel(self.client)
        logging.info("Watching workshop")
        self.client.add_message_handler(self.on_new_message)

    def on_new_message(self, message: events.NewMessage.Event):
        # Get chat, check it's one we know
        chat_id = message.chat_id
        chat = None
        for group in self.all_channels:
            if group.chat_id == chat_id:
                chat = group
                break
        if chat is None:
            return
        # Convert to our custom Message object
        new_message = Message.from_telegram_message(chat, message)
        # Pass to helpers
        for helper in self.helpers:
            try:
                helper.on_new_message(new_message)
            except Exception as e:
                logging.error(f"Helper {helper} threw an exception trying to handle message {new_message}.", exc_info=e)


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
