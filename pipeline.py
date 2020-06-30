import asyncio
import json
import logging
import sys
from typing import Dict, List, Union, Iterator, Optional

from telethon import events

from database import Database
from group import Group, Channel, WorkshopGroup, ChannelConfig, WorkshopConfig
from message import Message
from helpers import DuplicateHelper, TelegramGifHelper, VideoRotateHelper, VideoCutHelper, \
    VideoCropHelper, DownloadHelper, StabiliseHelper, QualityVideoHelper, MSGHelper, ImgurGalleryHelper, \
    AutoSceneSplitHelper
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient, message_data_from_telegram


class PipelineConfig:

    def __init__(self, config: Dict):
        self.channels = [ChannelConfig.from_json(x) for x in config['channels']]
        self.workshops = [WorkshopConfig.from_json(x) for x in config["workshop_groups"]]
        self.api_id = config["api_id"]
        self.api_hash = config["api_hash"]
        self.api_keys = config.get("api_keys", {})

    def initialise_pipeline(self) -> 'Pipeline':
        database = Database()
        client = TelegramClient(self.api_id, self.api_hash)
        client.synchronise_async(client.initialise())
        logging.info("Initialising channels")
        channels = client.synchronise_async(asyncio.gather(*[
            Channel.from_config(conf, client, database) for conf in self.channels
        ]))
        workshops = client.synchronise_async(asyncio.gather(*[
            WorkshopGroup.from_config(conf, client, database) for conf in self.workshops
        ]))
        pipe = Pipeline(database, client, channels, workshops, self.api_keys)
        logging.info("Initialised channels")
        return pipe


class Pipeline:
    def __init__(
            self,
            database: Database,
            client: TelegramClient,
            channels: List[Channel],
            workshops: List[WorkshopGroup],
            api_keys: Dict[str, Dict[str, str]]
    ):
        self.database = database
        self.channels = channels
        self.workshops = workshops
        self.client = client
        self.api_keys = api_keys
        self.worker = TaskWorker(3)
        self.helpers = {}

    @property
    def all_chats(self) -> List[Group]:
        channels = [x for x in self.channels]  # type: List[Group]
        for workshop in self.workshops:
            channels.append(workshop)
        return channels

    def chat_by_id(self, chat_id: int) -> Optional[Group]:
        for chat in self.all_chats:
            if chat.chat_data.chat_id == chat_id:
                return chat
        return None

    def initialise_helpers(self) -> None:
        logging.info("Initialising helpers")
        duplicate_helper = self.client.synchronise_async(self.initialise_duplicate_detector())
        helpers = [
            duplicate_helper,
            TelegramGifHelper(self.database, self.client, self.worker),
            VideoRotateHelper(self.database, self.client, self.worker),
            VideoCutHelper(self.database, self.client, self.worker),
            VideoCropHelper(self.database, self.client, self.worker),
            DownloadHelper(self.database, self.client, self.worker),
            StabiliseHelper(self.database, self.client, self.worker),
            QualityVideoHelper(self.database, self.client, self.worker),
            MSGHelper(self.database, self.client, self.worker),
            AutoSceneSplitHelper(self.database, self.client, self.worker)
        ]
        if "imgur" in self.api_keys:
            helpers.append(ImgurGalleryHelper(self.database, self.client, self.worker))
        for helper in helpers:
            self.helpers[helper.name] = helper
        logging.info(f"Initialised {len(self.helpers)} helpers")

    async def initialise_duplicate_detector(self) -> DuplicateHelper:
        helper = DuplicateHelper(self.database, self.client, self.worker)
        logging.info("Initialising DuplicateHelper")
        await helper.initialise_hashes(self.channels, self.workshops)
        logging.info("Initialised DuplicateHelper")
        return helper

    def watch_workshop(self) -> None:
        logging.info("Watching workshop")
        self.client.add_message_handler(self.on_new_message)
        self.client.add_delete_handler(self.on_deleted_message)
        self.client.client.run_until_disconnected()

    async def on_new_message(self, event: Union[events.NewMessage.Event, events.MessageEdited.Event]):
        # This is called for both new messages, and edited messages
        # Get chat, check it's one we know
        chat = self.chat_by_id(event.chat_id)
        if chat is None:
            logging.debug("Ignoring new message in other chat")
            return
        # Convert to our custom Message object. This will update message data, but not the video, for edited messages
        logging.info(f"New message in chat: {chat}")
        message_data = message_data_from_telegram(event.message)
        new_message = await Message.from_message_data(message_data, chat.chat_data, self.client)
        chat.messages.append(new_message)
        logging.info(f"New message initialised: {new_message}")
        # Pass to helpers
        await self.pass_message_to_handlers(chat, new_message)

    async def pass_message_to_handlers(self, chat: Group, new_message: Message):
        helper_results = await asyncio.gather(
            *(helper.on_new_message(chat, new_message) for helper in self.helpers.values()),
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
                    await self.pass_message_to_handlers(chat, reply_message)

    async def on_deleted_message(self, event: events.MessageDeleted.Event):
        # Get messages
        chat = self.chat_by_id(event.chat_id)
        messages = self.get_messages_for_delete_event(event)
        for message in messages:
            # Tell helpers
            helper_results = await asyncio.gather(
                *(helper.on_deleted_message(chat, message) for helper in self.helpers.values()),
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
            logging.info(f"Deleting message {message} from chat: {message.chat_data}")
            message.delete(self.database)
            chat.remove_message(message.message_data)

    def get_messages_for_delete_event(self, event: events.MessageDeleted.Event) -> Iterator[Message]:
        deleted_ids = event.deleted_ids
        if event.chat_id is None:
            return [
                message
                for workshop in self.workshops
                for message in workshop.messages
                if message.message_data.message_id in deleted_ids
            ]
        chat = self.chat_by_id(event.chat_id)
        if chat is None:
            return []
        return [message for message in chat.messages if message.message_data.message_id in deleted_ids]


def setup_logging() -> None:
    formatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler("pipeline.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


def setup_loop() -> None:
    if sys.platform == 'win32':
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)


if __name__ == "__main__":
    setup_loop()
    setup_logging()
    with open("config.json", "r") as c:
        CONF = json.load(c)
    pipeline_conf = PipelineConfig(CONF)
    pipeline = pipeline_conf.initialise_pipeline()
    pipeline.initialise_helpers()
    pipeline.watch_workshop()
