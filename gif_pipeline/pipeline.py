import asyncio
import logging
from typing import Dict, List, Iterator, Optional, Iterable, Union, Tuple

from telethon import events
from tqdm import tqdm

from gif_pipeline.chat_builder import ChannelBuilder, WorkshopBuilder
from gif_pipeline.database import Database
from gif_pipeline.chat import Chat, Channel, WorkshopGroup
from gif_pipeline.chat_config import ChannelConfig, WorkshopConfig
from gif_pipeline.helpers.delete_helper import DeleteHelper
from gif_pipeline.helpers.download_helper import DownloadHelper
from gif_pipeline.helpers.duplicate_helper import DuplicateHelper
from gif_pipeline.helpers.fa_helper import FAHelper
from gif_pipeline.helpers.ffprobe_helper import FFProbeHelper
from gif_pipeline.helpers.imgur_gallery_helper import ImgurGalleryHelper
from gif_pipeline.helpers.menu_helper import MenuHelper
from gif_pipeline.helpers.merge_helper import MergeHelper
from gif_pipeline.helpers.msg_helper import MSGHelper
from gif_pipeline.helpers.reverse_helper import ReverseHelper
from gif_pipeline.helpers.scene_split_helper import SceneSplitHelper
from gif_pipeline.helpers.send_helper import GifSendHelper
from gif_pipeline.helpers.stabilise_helper import StabiliseHelper
from gif_pipeline.helpers.telegram_gif_helper import TelegramGifHelper
from gif_pipeline.helpers.video_crop_helper import VideoCropHelper
from gif_pipeline.helpers.video_cut_helper import VideoCutHelper
from gif_pipeline.helpers.video_helper import VideoHelper
from gif_pipeline.helpers.video_rotate_helper import VideoRotateHelper
from gif_pipeline.helpers.zip_helper import ZipHelper
from gif_pipeline.menu_cache import MenuCache
from gif_pipeline.message import Message
from gif_pipeline.tasks.task_worker import TaskWorker, Bottleneck
from gif_pipeline.telegram_client import TelegramClient, message_data_from_telegram, chat_id_from_telegram
from gif_pipeline.utils import tqdm_gather

logger = logging.getLogger(__name__)


class PipelineConfig:

    def __init__(self, config: Dict):
        self.channels = [ChannelConfig.from_json(x) for x in config['channels']]
        self.workshops = [WorkshopConfig.from_json(x) for x in config["workshop_groups"]]
        self.workshops += [chan.queue for chan in self.channels if chan.queue is not None]
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
        channels, workshops = client.synchronise_async(self.initialise_chats(database, client))
        pipe = Pipeline(database, client, channels, workshops, self.api_keys)
        return pipe

    async def initialise_chats(
            self,
            database: Database,
            client: TelegramClient
    ) -> Tuple[List[Channel], List[WorkshopGroup]]:
        download_bottleneck = Bottleneck(3)
        workshop_builder = WorkshopBuilder(database, client, download_bottleneck)
        channel_builder = ChannelBuilder(database, client, download_bottleneck)
        # Get chat data for chat config
        logger.info("Initialising workshop data")
        workshop_data = await workshop_builder.get_chat_data(self.workshops)
        logger.info("Initialising channel data")
        channel_data = await channel_builder.get_chat_data(self.channels)

        message_inits = []
        logger.info("Listing messages in workshops")
        workshop_message_lists = await workshop_builder.get_message_inits(self.workshops, workshop_data)
        workshop_message_counts = [len(x) for x in workshop_message_lists]
        message_inits += [init for message_list in workshop_message_lists for init in message_list]
        logger.info("Listing messages in channels")
        channel_message_lists = await channel_builder.get_message_inits(self.channels, channel_data)
        channel_message_counts = [len(x) for x in channel_message_lists]
        message_inits += [init for message_list in channel_message_lists for init in message_list]

        logger.info("Downloading messages")
        all_messages = await tqdm_gather(message_inits, desc="Downloading messages")

        logger.info("Creating workshops")
        workshop_dict = {}
        for work_conf, work_data, message_count in zip(self.workshops, workshop_data, workshop_message_counts):
            work_messages = all_messages[:message_count]
            all_messages = all_messages[message_count:]
            workshop_dict[work_conf.handle] = WorkshopGroup(work_data, work_conf, work_messages, client)
        logger.info("Creating channels")
        channels = []
        for chan_conf, chan_data, message_count in zip(self.channels, channel_data, channel_message_counts):
            chan_messages = all_messages[:message_count]
            all_messages = all_messages[message_count:]
            queue = None
            if chan_conf.queue:
                queue = workshop_dict[chan_conf.queue.handle]
            channels.append(Channel(chan_data, chan_conf, chan_messages, client, queue))
        workshops = list(workshop_dict.values())

        logger.info("Cleaning up excess files from chats")
        for chat in tqdm([*channels, *workshops], desc="Cleaning up excess files from chats"):
            chat.cleanup_excess_files()

        logger.info("Initialised channels and workshops")
        return channels, workshops


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
    def all_chats(self) -> List[Chat]:
        channels = [x for x in self.channels]  # type: List[Chat]
        for workshop in self.workshops:
            channels.append(workshop)
        return channels

    @property
    def all_chat_ids(self) -> List[int]:
        return [chat.chat_data.chat_id for chat in self.all_chats]

    def chat_by_id(self, chat_id: int) -> Optional[Chat]:
        for chat in self.all_chats:
            if chat.chat_data.chat_id == chat_id:
                return chat
        return None

    def initialise_helpers(self) -> None:
        logging.info("Initialising helpers")
        duplicate_helper = self.client.synchronise_async(self.initialise_duplicate_detector())
        menu_helper = MenuHelper(self.database, self.client, self.worker, self.menu_cache)
        helpers = [
            duplicate_helper,
            menu_helper,
            TelegramGifHelper(self.database, self.client, self.worker),
            VideoRotateHelper(self.database, self.client, self.worker),
            VideoCutHelper(self.database, self.client, self.worker),
            VideoCropHelper(self.database, self.client, self.worker),
            DownloadHelper(self.database, self.client, self.worker),
            StabiliseHelper(self.database, self.client, self.worker),
            VideoHelper(self.database, self.client, self.worker),
            MSGHelper(self.database, self.client, self.worker),
            FAHelper(self.database, self.client, self.worker),
            SceneSplitHelper(self.database, self.client, self.worker, menu_helper),
            GifSendHelper(self.database, self.client, self.worker, self.channels, menu_helper),
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

    async def on_new_message(self, event: events.NewMessage.Event) -> None:
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

    async def pass_message_to_handlers(self, new_message: Message, chat: Chat = None):
        if chat is None:
            chat = self.chat_by_id(new_message.chat_data.chat_id)
        helper_results: Iterable[Union[BaseException, Optional[List[Message]]]] = await asyncio.gather(
            *(helper.on_new_message(chat, new_message) for helper in self.helpers.values()),
            return_exceptions=True
        )
        for helper, result in zip(self.helpers.keys(), helper_results):
            if isinstance(result, BaseException):
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
        # Get the menu
        menu = self.menu_cache.get_menu_by_message_id(event.chat_id, event.message_id)
        if not menu:
            logging.warning("Received a callback for a menu missing from cache")
            await event.answer("That menu is unrecognised.")
            return
        # Check button was pressed by the person who requested the menu
        if event.sender_id != menu.menu.owner_id:
            logging.info("User tried to press a button on a menu that wasn't theirs")
            await event.answer("This is not your menu, you are not authorised to use it.")
            return
        # Check if menu has already been clicked
        if menu.clicked:
            # Menu already clicked
            logging.info("Callback received for a menu which has already been clicked")
            await event.answer("That menu has already been clicked.")
            return
        # Hand callback queries to helpers
        helper_results: Iterable[Union[BaseException, Optional[List[Message]]]] = await asyncio.gather(
            *(helper.on_callback_query(event.data, menu) for helper in self.helpers.values()),
            return_exceptions=True
        )
        answered = False
        for helper, result in zip(self.helpers.keys(), helper_results):
            if isinstance(result, BaseException):
                logging.error(
                    f"Helper {helper} threw an exception trying to handle callback query {event}.",
                    exc_info=result
                )
            elif result:
                for reply_message in result:
                    await self.pass_message_to_handlers(reply_message)
            # Check for result is None because empty list would be an answer, None is not
            if result is not None and not answered:
                await event.answer()
