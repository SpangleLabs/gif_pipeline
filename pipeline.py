import asyncio
import json
import logging
import sys
from typing import Dict, List, Union, Iterator

from telethon import events

from database import Database
from group import Group, Channel, WorkshopGroup
from message import Message
from helpers import DuplicateHelper, TelegramGifHelper, VideoRotateHelper, VideoCutHelper, \
    VideoCropHelper, DownloadHelper, StabiliseHelper, QualityVideoHelper, MSGHelper, ImgurGalleryHelper, \
    AutoSceneSplitHelper
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient


class Pipeline:
    def __init__(self, config: Dict):
        self.database = Database()
        self.channels = [Channel.from_json(x) for x in config['channels']]
        self.workshops = [WorkshopGroup(x["handle"]) for x in config["workshop_groups"]]
        self.client = TelegramClient(config['api_id'], config['api_hash'])
        self.api_keys = config.get("api_keys", {})
        self.worker = TaskWorker(3)
        self.helpers = {}

    @property
    def all_chats(self) -> List[Group]:
        channels = [x for x in self.channels]  # type: List[Group]
        for workshop in self.workshops:
            channels.append(workshop)
        return channels

    def initialise_channels(self):
        logging.info("Initialising channels")
        # Initialise client
        self.client.synchronise_async(self.client.initialise())
        # Scrape channels
        chat_init_awaitables = [
            chan.initialise(self.client, self.database) for chan in self.all_chats
        ]
        self.client.synchronise_async(asyncio.wait(chat_init_awaitables))
        logging.info("Initialised channels")

    def initialise_helpers(self):
        logging.info("Initialising helpers")
        duplicate_helper = self.client.synchronise_async(self.initialise_duplicate_detector())
        helpers = [
            duplicate_helper,
            TelegramGifHelper(self.client, self.worker),
            VideoRotateHelper(self.client, self.worker),
            VideoCutHelper(self.client, self.worker),
            VideoCropHelper(self.client, self.worker),
            DownloadHelper(self.client, self.worker),
            StabiliseHelper(self.client, self.worker),
            QualityVideoHelper(self.client, self.worker),
            MSGHelper(self.client, self.worker),
            AutoSceneSplitHelper(self.client, self.worker)
        ]
        if "imgur" in self.api_keys:
            helpers.append(ImgurGalleryHelper(self.client, self.worker, self.api_keys["imgur"]["client_id"]))
        for helper in helpers:
            self.helpers[helper.name] = helper
        logging.info(f"Initialised {len(self.helpers)} helpers")

    async def initialise_duplicate_detector(self) -> DuplicateHelper:
        helper = DuplicateHelper(self.client, self.worker)
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
        for group in self.all_chats:
            if group.chat_id == chat_id:
                chat = group
                break
        if chat is None:
            logging.debug("Ignoring new message in other chat")
            return
        # Convert to our custom Message object. This will update message data, but not the video, for edited messages
        logging.info(f"New message in chat: {chat}")
        new_message = await Message.from_telegram_message(chat, message.message)
        chat.messages[new_message.message_id] = new_message
        await new_message.initialise_directory(self.client)
        logging.info(f"New message initialised: {new_message}")
        # Pass to helpers
        await self.pass_message_to_handlers(new_message)

    async def pass_message_to_handlers(self, new_message: Message):
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
            elif result:
                for reply_message in result:
                    await self.pass_message_to_handlers(reply_message)

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

    def get_messages_for_delete_event(self, event: events.MessageDeleted.Event) -> Iterator[Message]:
        deleted_ids = event.deleted_ids
        channel_id = event.chat_id
        if channel_id is None:
            all_messages = [
                workshop.messages.get(deleted_id)
                for deleted_id in deleted_ids
                for workshop in self.workshops
            ]
            return filter(None, all_messages)
        for channel in self.all_chats:
            if channel.chat_id == channel_id:
                return filter(None, [channel.messages.get(deleted_id) for deleted_id in deleted_ids])
        return []


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
