import asyncio
import json
import logging
import sys
from typing import Dict, List, Union

from telethon import events

from channel import Channel, WorkshopGroup, Message, Group
from helpers import DuplicateHelper, TelegramGifHelper, VideoRotateHelper, VideoCutHelper, \
    VideoCropHelper, DownloadHelper
from telegram_client import TelegramClient


class Pipeline:
    def __init__(self, config: Dict):
        self.channels = [Channel.from_json(x) for x in config['channels']]
        self.workshops = [WorkshopGroup(x["handle"]) for x in config["workshop_groups"]]
        self.client = TelegramClient(config['api_id'], config['api_hash'])
        self.helpers = {}

    @property
    def all_channels(self) -> List[Group]:
        channels = [x for x in self.channels]  # type: List[Group]
        for workshop in self.workshops:
            channels.append(workshop)
        return channels

    def initialise_channels(self):
        logging.info("Initialising channels")
        # Scrape channels
        channel_init_awaitables = [chan.initialise_channel(self.client) for chan in self.all_channels]
        self.client.synchronise_async(asyncio.wait(channel_init_awaitables))
        logging.info("Initialised channels")

    def initialise_helpers(self):
        logging.info("Initialising helpers")
        duplicate_helper = self.client.synchronise_async(self.initialise_duplicate_detector())
        helpers = [
            duplicate_helper,
            TelegramGifHelper(self.client),
            VideoRotateHelper(self.client),
            VideoCutHelper(self.client),
            VideoCropHelper(self.client),
            DownloadHelper(self.client)
        ]
        for helper in helpers:
            self.helpers[helper.name] = helper
        logging.info(f"Initialised {len(self.helpers)} helpers")

    async def initialise_duplicate_detector(self) -> DuplicateHelper:
        helper = DuplicateHelper(self.client)
        logging.info("Initialising DuplicateHelper")
        await helper.initialise_hashes(self.channels, self.workshops)
        logging.info("Initialised DuplicateHelper")
        return helper

    def watch_workshop(self):
        logging.info("Watching workshop")
        self.client.add_message_handler(self.on_new_message)
        self.client.add_delete_handler(self.on_deleted_message)
        self.client.client.run_until_disconnected()

    async def on_new_message(self, message: Union[events.NewMessage.Event, events.MessageEdited.Event]):
        # This is called for both new messages, and edited messages
        # Get chat, check it's one we know
        chat_id = message.chat_id
        chat = None
        for group in self.all_channels:
            if group.chat_id == chat_id:
                chat = group
                break
        if chat is None:
            logging.debug("Ignoring new message in other chat")
            return
        # Convert to our custom Message object. This will update message data, but not the video, for edited messages
        logging.info(f"New message in chat: {chat}")
        new_message = await Message.from_telegram_message(chat, message)
        chat.messages[new_message.message_id] = new_message
        await new_message.initialise_directory(self.client)
        logging.info(f"New message initialised: {new_message}")
        # Pass to helpers
        helper_results = await asyncio.gather(
            *(helper.on_new_message(new_message) for helper in self.helpers.values()),
            return_exceptions=True
        )
        results_dict = dict(zip(self.helpers.keys(), helper_results))
        for helper, result in results_dict.items():
            if isinstance(result, Exception):
                logging.error(
                    f"Helper {helper} threw an exception trying to handle message {new_message}.",
                    exc_info=result
                )

    async def on_deleted_message(self, event: events.MessageDeleted.Event):
        # Get messages
        messages = self.get_messages_for_delete_event(event)
        for message in messages:
            # Tell helpers
            helper_results = await asyncio.gather(
                *(helper.on_deleted_message(message) for helper in self.helpers.values()),
                return_exceptions=True
            )
            results_dict = dict(zip(self.helpers.keys(), helper_results))
            for helper, result in results_dict.items():
                if isinstance(result, Exception):
                    logging.error(
                        f"Helper {helper} threw an exception trying to handle deleting message {message}.",
                        exc_info=result
                    )
            # Remove messages from store
            logging.info(f"Deleting message {message} from chat: {message.channel}")
            message.delete_directory()
            message.channel.messages.pop(message.message_id, None)

    def get_messages_for_delete_event(self, event: events.MessageDeleted.Event):
        deleted_ids = event.deleted_ids
        channel_id = event.chat_id
        if channel_id is None:
            all_messages = [
                workshop.messages.get(deleted_id)
                for deleted_id in deleted_ids
                for workshop in self.workshops
            ]
            return filter(None, all_messages)
        for channel in self.all_channels:
            if channel.chat_id == channel_id:
                return filter(None, [channel.messages.get(deleted_id) for deleted_id in deleted_ids])


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


def setup_loop():
    if sys.platform == 'win32':
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)


if __name__ == "__main__":
    setup_loop()
    setup_logging()
    with open("config.json", "r") as c:
        conf = json.load(c)
    pipeline = Pipeline(conf)
    pipeline.initialise_channels()
    pipeline.initialise_helpers()
    pipeline.watch_workshop()
