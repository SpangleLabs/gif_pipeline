import asyncio
import json
import logging
import sys
from typing import Dict, List, Iterator, Optional

from telethon import events

from database import Database
from group import Group, Channel, WorkshopGroup, ChannelConfig, WorkshopConfig
from helpers.delete_helper import DeleteHelper
from helpers.download_helper import DownloadHelper
from helpers.duplicate_helper import DuplicateHelper
from helpers.fa_helper import FAHelper
from helpers.ffprobe_helper import FFProbeHelper
from helpers.imgur_gallery_helper import ImgurGalleryHelper
from helpers.merge_helper import MergeHelper
from helpers.msg_helper import MSGHelper
from helpers.reverse_helper import ReverseHelper
from helpers.scene_split_helper import SceneSplitHelper
from helpers.send_helper import GifSendHelper
from helpers.stabilise_helper import StabiliseHelper
from helpers.telegram_gif_helper import TelegramGifHelper
from helpers.video_crop_helper import VideoCropHelper
from helpers.video_cut_helper import VideoCutHelper
from helpers.video_helper import VideoHelper
from helpers.video_rotate_helper import VideoRotateHelper
from helpers.zip_helper import ZipHelper
from menu_cache import MenuCache
from message import Message
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient, message_data_from_telegram, chat_id_from_telegram


class PipelineConfig:

    def __init__(self, config: Dict):
        self.channels = [ChannelConfig.from_json(x) for x in config['channels']]
        self.workshops = [WorkshopConfig.from_json(x) for x in config["workshop_groups"]]
        self.api_id = config["api_id"]
        self.api_hash = config["api_hash"]
        # Pipeline bot, handles video editing and sending to channels
        self.pipeline_bot_token = config.get("pipeline_bot_token")
        # Public bot, handles public queries for gifs and searches
        self.public_bot_token = config.get("public_bot_token")
        # API keys for external services
        self.api_keys = config.get("api_keys", {})

    def initialise_pipeline(self) -> 'Pipeline':
        database = Database()
        client = TelegramClient(self.api_id, self.api_hash, self.pipeline_bot_token, self.public_bot_token)
        client.synchronise_async(client.initialise())
        logging.info("Initialising channels")
        channels = self.get_channels(client, database)
        workshops = self.get_workshops(client, database)
        pipe = Pipeline(database, client, channels, workshops, self.api_keys)
        logging.info("Initialised channels")
        return pipe

    def get_channels(self, client: TelegramClient, database: Database) -> List[Channel]:
        db_channels = database.list_channels()
        channel_inits = []
        for conf in self.channels:
            matching_db_chat = next(
                (chat for chat in db_channels if chat.username == conf.handle or chat.chat_id == conf.handle),
                None
            )
            if matching_db_chat:
                channel_inits.append(Channel.from_data(matching_db_chat, conf, client, database))
            else:
                channel_inits.append(Channel.from_config(conf, client, database))
        channels = client.synchronise_async(asyncio.gather(*channel_inits))
        return channels

    def get_workshops(self, client: TelegramClient, database: Database) -> List[WorkshopGroup]:
        db_channels = database.list_workshops()
        workshop_inits = []
        for conf in self.workshops:
            matching_db_chat = next(
                (chat for chat in db_channels if chat.username == conf.handle or chat.chat_id == conf.handle),
                None
            )
            if matching_db_chat:
                workshop_inits.append(WorkshopGroup.from_data(matching_db_chat, conf, client, database))
            else:
                workshop_inits.append(WorkshopGroup.from_config(conf, client, database))
        channels = client.synchronise_async(asyncio.gather(*workshop_inits))
        return channels


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
        self.menu_cache = MenuCache()

    @property
    def all_chats(self) -> List[Group]:
        channels = [x for x in self.channels]  # type: List[Group]
        for workshop in self.workshops:
            channels.append(workshop)
        return channels

    @property
    def all_chat_ids(self) -> List[int]:
        return [chat.chat_data.chat_id for chat in self.all_chats]

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
            VideoHelper(self.database, self.client, self.worker),
            MSGHelper(self.database, self.client, self.worker),
            FAHelper(self.database, self.client, self.worker),
            SceneSplitHelper(self.database, self.client, self.worker, self.menu_cache),
            GifSendHelper(self.database, self.client, self.worker, self.channels, self.menu_cache),
            DeleteHelper(self.database, self.client, self.worker),
            MergeHelper(self.database, self.client, self.worker),
            ReverseHelper(self.database, self.client, self.worker),
            FFProbeHelper(self.database, self.client, self.worker),
            ZipHelper(self.database, self.client, self.worker)
        ]
        if "imgur" in self.api_keys:
            helpers.append(
                ImgurGalleryHelper(self.database, self.client, self.worker, self.api_keys["imgur"]["client_id"]))
        for helper in helpers:
            self.helpers[helper.name] = helper
        logging.info(f"Initialised {len(self.helpers)} helpers")

    async def initialise_duplicate_detector(self) -> DuplicateHelper:
        helper = DuplicateHelper(self.database, self.client, self.worker)
        logging.info("Initialising DuplicateHelper")
        await helper.initialise_hashes(self.workshops)
        logging.info("Initialised DuplicateHelper")
        return helper

    def watch_workshop(self) -> None:
        logging.info("Watching workshop")
        self.client.add_message_handler(self.on_new_message, self.all_chat_ids)
        self.client.add_edit_handler(self.on_edit_message, self.all_chat_ids)
        self.client.add_delete_handler(self.on_deleted_message)
        self.client.add_callback_query_handler(self.on_callback_query)
        self.client.client.run_until_disconnected()

    async def on_edit_message(self, event: events.MessageEdited.Event):
        # Get chat, check it's one we know
        chat = self.chat_by_id(chat_id_from_telegram(event.message))
        if chat is None:
            logging.debug("Ignoring edited message in other chat, which must have slipped through")
            return
        # Convert to our custom Message object. This will update message data, but not the video, for edited messages
        logging.info(f"Edited message in chat: {chat}")
        message_data = message_data_from_telegram(event.message)
        new_message = await Message.from_message_data(message_data, chat.chat_data, self.client)
        chat.remove_message(message_data)
        chat.add_message(new_message)
        self.database.save_message(new_message.message_data)
        logging.info(f"Edited message initialised: {new_message}")

    async def on_new_message(self, event: events.NewMessage.Event):
        # This is called just for new messages
        # Get chat, check it's one we know
        chat = self.chat_by_id(chat_id_from_telegram(event.message))
        if chat is None:
            logging.debug("Ignoring new message in other chat, which must have slipped through")
            return
        # Convert to our custom Message object. This will update message data, but not the video, for edited messages
        logging.info(f"New message in chat: {chat}")
        message_data = message_data_from_telegram(event.message)
        new_message = await Message.from_message_data(message_data, chat.chat_data, self.client)
        chat.add_message(new_message)
        self.database.save_message(new_message.message_data)
        logging.info(f"New message initialised: {new_message}")
        # Pass to helpers
        await self.pass_message_to_handlers(new_message, chat)

    async def pass_message_to_handlers(self, new_message: Message, chat: Group = None):
        if chat is None:
            chat = self.chat_by_id(new_message.chat_data.chat_id)
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
                    await self.pass_message_to_handlers(reply_message)

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

    async def on_callback_query(self, event: events.CallbackQuery.Event):
        # Get chat, check it's one we know
        chat = self.chat_by_id(chat_id_from_telegram(event))
        if chat is None:
            logging.debug("Ignoring new message in other chat, which must have slipped through")
            return
        # Check button was pressed by the person who requested the menu
        if event.sender_id != self.menu_cache.get_sender_for_message(event.chat_id, event.message_id):
            logging.info("User tried to press a button on a menu that wasn't theirs")
            await event.answer("This is not your menu, you are not authorised to use it.")
            return
        # Hand callback queries to helpers
        helper_results = await asyncio.gather(
            *(helper.on_callback_query(chat, event.data, event.sender_id) for helper in self.helpers.values()),
            return_exceptions=True
        )
        results_dict = dict(zip(self.helpers.keys(), helper_results))
        for helper, result in results_dict.items():
            if isinstance(result, Exception):
                logging.error(
                    f"Helper {helper} threw an exception trying to handle callback query {event}.",
                    exc_info=result
                )
            elif result:
                for reply_message in result:
                    await self.pass_message_to_handlers(reply_message)


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
