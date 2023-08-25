import asyncio
import logging
from typing import Dict, List, Optional, Iterable, Union, Tuple

from prometheus_client import Info, start_http_server
from telethon import events
from tqdm import tqdm

from gif_pipeline import _version
from gif_pipeline.chat_builder import ChannelBuilder, WorkshopBuilder
from gif_pipeline.database import Database
from gif_pipeline.chat import Chat, Channel, WorkshopGroup
from gif_pipeline.chat_config import ChannelConfig, WorkshopConfig
from gif_pipeline.helpers.audio_helper import AudioHelper
from gif_pipeline.helpers.channel_fwd_tag_helper import ChannelFwdTagHelper
from gif_pipeline.helpers.chart_helper import ChartHelper
from gif_pipeline.helpers.chunk_split_helper import ChunkSplitHelper
from gif_pipeline.helpers.delete_helper import DeleteHelper
from gif_pipeline.helpers.download_helper import DownloadHelper
from gif_pipeline.helpers.duplicate_helper import DuplicateHelper
from gif_pipeline.helpers.fa_helper import FAHelper
from gif_pipeline.helpers.ffprobe_helper import FFProbeHelper
from gif_pipeline.helpers.find_helper import FindHelper
from gif_pipeline.helpers.imgur_gallery_helper import ImgurGalleryHelper
from gif_pipeline.helpers.menu_helper import MenuHelper
from gif_pipeline.helpers.merge_helper import MergeHelper
from gif_pipeline.helpers.msg_helper import MSGHelper
from gif_pipeline.helpers.public.public_tag_helper import PublicTagHelper
from gif_pipeline.helpers.reverse_helper import ReverseHelper
from gif_pipeline.helpers.scene_split_helper import SceneSplitHelper
from gif_pipeline.helpers.schedule_helper import ScheduleHelper
from gif_pipeline.helpers.send_helper import GifSendHelper
from gif_pipeline.helpers.stabilise_helper import StabiliseHelper
from gif_pipeline.helpers.subscription_helper import SubscriptionHelper
from gif_pipeline.helpers.tag_helper import TagHelper
from gif_pipeline.helpers.telegram_gif_helper import TelegramGifHelper
from gif_pipeline.helpers.thumbnail_helper import ThumbnailHelper
from gif_pipeline.helpers.update_yt_dl_helper import UpdateYoutubeDlHelper
from gif_pipeline.helpers.video_crop_helper import VideoCropHelper
from gif_pipeline.helpers.video_cut_helper import VideoCutHelper
from gif_pipeline.helpers.video_helper import VideoHelper
from gif_pipeline.helpers.video_rotate_helper import VideoRotateHelper
from gif_pipeline.helpers.zip_helper import ZipHelper
from gif_pipeline.menu_cache import MenuCache
from gif_pipeline.message import Message, MessageData
from gif_pipeline.startup_monitor import StartupMonitor, StartupState
from gif_pipeline.tag_manager import TagManager
from gif_pipeline.tasks.task_worker import TaskWorker, Bottleneck
from gif_pipeline.telegram_client import TelegramClient, message_data_from_telegram, chat_id_from_telegram
from gif_pipeline.utils import tqdm_gather

logger = logging.getLogger(__name__)

version_info = Info(
    "gif_pipeline_version",
    "Version of gif pipeline currently running"
)

PROM_PORT = 7180


class PipelineConfig:

    def __init__(self, config: Dict):
        start_http_server(PROM_PORT)
        version_info.info({
            "version": _version.__VERSION__
        })
        self.startup_monitor = StartupMonitor()
        self.startup_monitor.set_state(StartupState.LOADING_CONFIG)
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
        self.startup_monitor.set_state(StartupState.CREATING_DATABASE)
        database = Database()
        self.startup_monitor.set_state(StartupState.CONNECTING_TELEGRAM)
        client = TelegramClient(self.api_id, self.api_hash, self.pipeline_bot_token, self.public_bot_token)
        client.synchronise_async(client.initialise())
        channels, workshops = client.synchronise_async(self.initialise_chats(database, client))
        self.startup_monitor.set_state(StartupState.CREATING_PIPELINE)
        pipe = Pipeline(database, client, channels, workshops, self.api_keys, self.startup_monitor)
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
        self.startup_monitor.set_state(StartupState.INITIALISING_CHAT_DATA)
        logger.info("Initialising workshop data")
        workshop_data = await workshop_builder.get_chat_data(self.workshops)
        logger.info("Initialising channel data")
        channel_data = await channel_builder.get_chat_data(self.channels)

        message_inits = []
        self.startup_monitor.set_state(StartupState.LISTING_WORKSHOP_MESSAGES)
        logger.info("Listing messages in workshops")
        workshop_message_lists = await workshop_builder.get_message_inits(self.workshops, workshop_data)
        workshop_message_counts = [len(x) for x in workshop_message_lists]
        message_inits += [init for message_list in workshop_message_lists for init in message_list]
        self.startup_monitor.set_state(StartupState.LISTING_CHANNEL_MESSAGES)
        logger.info("Listing messages in channels")
        channel_message_lists = await channel_builder.get_message_inits(self.channels, channel_data)
        channel_message_counts = [len(x) for x in channel_message_lists]
        message_inits += [init for message_list in channel_message_lists for init in message_list]

        self.startup_monitor.set_state(StartupState.DOWNLOADING_MESSAGES)
        logger.info("Downloading messages")
        all_messages = await tqdm_gather(message_inits, desc="Downloading messages")

        logger.info("Creating workshops")
        self.startup_monitor.set_state(StartupState.CREATING_WORKSHOPS)
        workshop_dict = {}
        for work_conf, work_data, message_count in zip(self.workshops, workshop_data, workshop_message_counts):
            work_messages = all_messages[:message_count]
            all_messages = all_messages[message_count:]
            workshop_dict[work_conf.handle] = WorkshopGroup(work_data, work_conf, work_messages, client)
        logger.info("Creating channels")
        self.startup_monitor.set_state(StartupState.CREATING_CHANNELS)
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
        self.startup_monitor.set_state(StartupState.CLEANING_UP_CHAT_FILES)
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
            api_keys: Dict[str, Dict[str, str]],
            startup_monitor: StartupMonitor
    ):
        self.database = database
        self.channels = channels
        self.workshops = workshops
        self.client = client
        self.api_keys = api_keys
        self.worker = TaskWorker(3)
        self.helpers = {}
        self.public_helpers = {}
        self.menu_cache = MenuCache(database)  # MenuHelper later populates this from database
        self.download_bottleneck = Bottleneck(3)
        self.startup_monitor = startup_monitor

    @property
    def all_chats(self) -> List[Chat]:
        return [*self.channels, *self.workshops]

    @property
    def all_chat_ids(self) -> List[int]:
        return [chat.chat_data.chat_id for chat in self.all_chats]

    def chat_by_id(self, chat_id: int) -> Optional[Chat]:
        for chat in self.all_chats:
            if chat.chat_data.chat_id == chat_id:
                return chat
        return None

    def channel_by_handle(self, name: str) -> Optional[Channel]:
        name = name.lstrip("@")
        for chat in self.channels:
            if chat.chat_data.matches_handle(name):
                return chat
        return None

    def get_message_for_handle_and_id(self, handle: Union[int, str], message_id: int) -> Optional[Message]:
        for chat in self.all_chats:
            if chat.chat_data.matches_handle(str(handle)):
                return chat.message_by_id(message_id)
        return None

    def get_message_for_link(self, link: str) -> Optional[Message]:
        link_split = link.strip("/").split("/")
        if len(link_split) < 2:
            return None
        message_id = int(link_split[-1])
        handle = link_split[-2]
        return self.get_message_for_handle_and_id(handle, message_id)

    def initialise_helpers(self) -> None:
        logger.info("Initialising helpers")
        self.startup_monitor.set_state(StartupState.INITIALISING_DUPLICATE_DETECTOR)
        duplicate_helper = self.client.synchronise_async(self.initialise_duplicate_detector())
        self.startup_monitor.set_state(StartupState.INITIALISING_HELPERS)
        tag_manager = TagManager(self.database)
        delete_helper = DeleteHelper(self.database, self.client, self.worker, self.menu_cache)
        menu_helper = MenuHelper(self.database, self.client, self.worker, self, delete_helper, tag_manager)
        twitter_keys = self.api_keys.get("twitter", {})
        send_helper = GifSendHelper(self.database, self.client, self.worker, self.channels, menu_helper, twitter_keys)
        schedule_helper = ScheduleHelper(
            self.database,
            self.client,
            self.worker,
            self.channels,
            menu_helper,
            send_helper,
            delete_helper,
            tag_manager
        )
        download_helper = DownloadHelper(self.database, self.client, self.worker)
        subscription_helper = SubscriptionHelper(
            self.database,
            self.client,
            self.worker,
            self,
            duplicate_helper,
            download_helper,
            self.api_keys
        )
        ffprobe_helper = FFProbeHelper(self.database, self.client, self.worker)
        helpers = [
            duplicate_helper,
            menu_helper,
            TelegramGifHelper(self.database, self.client, self.worker),
            VideoRotateHelper(self.database, self.client, self.worker),
            VideoCutHelper(self.database, self.client, self.worker),
            VideoCropHelper(self.database, self.client, self.worker),
            download_helper,
            StabiliseHelper(self.database, self.client, self.worker),
            VideoHelper(self.database, self.client, self.worker),
            AudioHelper(self.database, self.client, self.worker),
            MSGHelper(self.database, self.client, self.worker),
            FAHelper(self.database, self.client, self.worker),
            SceneSplitHelper(self.database, self.client, self.worker, menu_helper),
            ChunkSplitHelper(self.database, self.client, self.worker, ffprobe_helper),
            send_helper,
            delete_helper,
            MergeHelper(self.database, self.client, self.worker),
            ReverseHelper(self.database, self.client, self.worker),
            ffprobe_helper,
            ZipHelper(self.database, self.client, self.worker),
            TagHelper(self.database, self.client, self.worker, self),
            ChannelFwdTagHelper(self.database, self.client, self.worker),
            UpdateYoutubeDlHelper(self.database, self.client, self.worker),
            ChartHelper(self.database, self.client, self.worker, self, tag_manager),
            schedule_helper,
            subscription_helper,
            FindHelper(self.database, self.client, self.worker, duplicate_helper, download_helper),
            ThumbnailHelper(self.database, self.client, self.worker, self),
        ]
        if "imgur" in self.api_keys:
            helpers.append(
                ImgurGalleryHelper(self.database, self.client, self.worker, self.api_keys["imgur"]["client_id"]))
        for helper in helpers:
            self.helpers[helper.name] = helper
        # Check yt-dl install
        self.startup_monitor.set_state(StartupState.INSTALLING_YT_DL)
        self.client.synchronise_async(download_helper.check_yt_dl())
        # Load menus from database
        self.startup_monitor.set_state(StartupState.LOADING_MENUS)
        self.client.synchronise_async(menu_helper.refresh_from_database())
        # Load schedule helper and subscription helper
        self.startup_monitor.set_state(StartupState.INITIALISING_SCHEDULES)
        self.client.synchronise_async(schedule_helper.initialise())
        self.startup_monitor.set_state(StartupState.INITIALISING_SUBSCRIPTIONS)
        self.client.synchronise_async(subscription_helper.initialise())
        # Helpers complete
        logger.info(f"Initialised {len(self.helpers)} helpers")
        # Set up public helpers
        self.startup_monitor.set_state(StartupState.INITIALISING_PUBLIC_HELPERS)
        public_helpers = [
            PublicTagHelper(self.database, self.client, self.worker, self)
        ]
        for helper in public_helpers:
            self.public_helpers[helper.name] = helper
        logger.info(f"Initialised {len(self.public_helpers)} public helpers")

    async def initialise_duplicate_detector(self) -> DuplicateHelper:
        helper = DuplicateHelper(self.database, self.client, self.worker)
        logger.info("Initialising DuplicateHelper")
        await helper.initialise_hashes(self.workshops)
        logger.info("Initialised DuplicateHelper")
        return helper

    def watch_workshop(self) -> None:
        # Set status to running
        self.startup_monitor.set_running()
        logger.info("Registering handlers")
        # Set up handlers
        self.client.add_message_handler(self.on_new_message, self.all_chat_ids)
        self.client.add_public_message_handler(self.pass_message_to_public_handlers)
        self.client.add_edit_handler(self.on_edit_message, self.all_chat_ids)
        self.client.add_delete_handler(self.on_deleted_message)
        self.client.add_callback_query_handler(self.on_callback_query)
        logger.info("Handlers registered, watching workshops")
        self.client.client.run_until_disconnected()

    async def on_edit_message(self, event: events.MessageEdited.Event):
        # Get chat, check it's one we know
        chat = self.chat_by_id(chat_id_from_telegram(event.message))
        if chat is None:
            logger.debug("Ignoring edited message in other chat, which must have slipped through")
            return
        # Convert to our custom Message object. This will update message data, but not the video, for edited messages
        logger.info(f"Edited message in chat: {chat}")
        message_data = message_data_from_telegram(event.message)
        new_message = await self.download_bottleneck.await_run(
            Message.from_message_data(message_data, chat.chat_data, self.client)
        )
        chat.remove_message(message_data)
        chat.add_message(new_message)
        self.database.save_message(new_message.message_data)
        logger.info(f"Edited message initialised: {new_message}")

    async def on_new_message(self, event: events.NewMessage.Event) -> None:
        # This is called just for new messages
        # Get chat, check it's one we know
        chat = self.chat_by_id(chat_id_from_telegram(event.message))
        if chat is None:
            logger.debug("Ignoring new message in other chat, which must have slipped through")
            return
        # Convert to our custom Message object. This will update message data, but not the video, for edited messages
        logger.info(f"New message in chat: {chat}")
        message_data = message_data_from_telegram(event.message)
        new_message = await self.download_bottleneck.await_run(
            Message.from_message_data(message_data, chat.chat_data, self.client)
        )
        chat.add_message(new_message)
        self.database.save_message(new_message.message_data)
        logger.info(f"New message initialised: {new_message}")
        # Pass to helpers
        await self.pass_message_to_handlers(new_message, chat)

    async def pass_message_to_handlers(self, new_message: Message, chat: Chat = None):
        if chat is None:
            chat = self.chat_by_id(new_message.chat_data.chat_id)
        # If any helpers say that a message is priority, send only to those helpers
        priority = any(helper.is_priority(chat, new_message) for helper in self.helpers.values())
        helpers = {key: val for key, val in self.helpers.items() if not priority or val.is_priority(chat, new_message)}
        # Call the helpers
        helper_results: Iterable[Union[BaseException, Optional[List[Message]]]] = await asyncio.gather(
            *(helper.on_new_message(chat, new_message) for helper in helpers.values()),
            return_exceptions=True
        )
        # Handle helper results
        for helper, result in zip(helpers.keys(), helper_results):
            if isinstance(result, BaseException):
                logger.error(
                    f"Helper {helper} threw an exception trying to handle message {new_message}.",
                    exc_info=result
                )
            elif result:
                for reply_message in result:
                    await self.pass_message_to_handlers(reply_message)

    async def pass_message_to_public_handlers(self, event: events.NewMessage.Event):
        logger.info(f"New public message: {event}")
        helper_results: Iterable[Union[BaseException, Optional[List[MessageData]]]] = await asyncio.gather(
            *(helper.on_new_message(event.message) for helper in self.public_helpers.values()),
            return_exceptions=True
        )
        for helper, result in zip(self.public_helpers.keys(), helper_results):
            if isinstance(result, BaseException):
                logger.error(
                    f"Public helper {helper} threw an exception trying to handle message {event}.",
                    exc_info=result
                )

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
                    logger.error(
                        f"Helper {helper} threw an exception trying to handle deleting message {message}.",
                        exc_info=result
                    )
            # If it's a menu, remove that
            self.menu_cache.remove_menu_by_message(message)
            # Remove messages from store
            logger.info(f"Deleting message {message} from chat: {message.chat_data}")
            message.delete(self.database)
            chat.remove_message(message.message_data)

    def get_messages_for_delete_event(self, event: events.MessageDeleted.Event) -> Iterable[Message]:
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
            logger.debug("Ignoring new message in other chat, which must have slipped through")
            return
        # Get the menu
        menu = self.menu_cache.get_menu_by_message_id(event.chat_id, event.message_id)
        if not menu:
            # Handle stateless menu callbacks
            logger.debug("Received a callback for a stateless menu")
            return await self.on_stateless_callback(event, chat)
        # Check button was pressed by someone who was allowed to press it
        if not menu.menu.allows_sender(event.sender_id):
            logger.info("User tried to press a button on a menu that wasn't theirs")
            await event.answer("This is not your menu, you are not authorised to use it.")
            return
        # Check if menu has already been clicked
        if menu.clicked:
            # Menu already clicked
            logger.info("Callback received for a menu which has already been clicked")
            await event.answer("That menu has already been clicked.")
            return
        # Hand callback queries to helpers
        helper_results: Iterable[Union[BaseException, Optional[List[Message]]]] = await asyncio.gather(
            *(helper.on_callback_query(event.data, menu, event.sender_id) for helper in self.helpers.values()),
            return_exceptions=True
        )
        answered = False
        for helper, result in zip(self.helpers.keys(), helper_results):
            if isinstance(result, BaseException):
                logger.error(
                    f"Helper {helper} threw an exception trying to handle callback query {event}.",
                    exc_info=result
                )
            elif result:
                for reply_message in result:
                    await self.pass_message_to_handlers(reply_message)
            # Check for result is None because empty list would be an answer, None is not
            if result is not None and not answered:
                await event.answer()

    async def on_stateless_callback(self, event: events.CallbackQuery.Event, chat: Chat) -> None:
        # Get message
        msg = chat.message_by_id(event.message_id)
        # Handle callback query
        helper_results: Iterable[Union[BaseException, Optional[List[Message]]]] = await asyncio.gather(
            *(helper.on_stateless_callback(event.data, chat, msg, event.sender_id) for helper in self.helpers.values()),
            return_exceptions=True
        )
        answered = False
        for helper, result in zip(self.helpers.keys(), helper_results):
            if isinstance(result, BaseException):
                logger.error(
                    f"Helper {helper} threw an exception trying to handle stateless callback query: {event}.",
                    exc_info=result
                )
            elif result:
                for reply_message in result:
                    await self.pass_message_to_handlers(reply_message)
            # Check for result is None because empty list would be an answer, None is not
            if result is not None and not answered:
                await event.answer()
