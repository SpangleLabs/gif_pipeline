import json
from typing import Optional, List, Tuple, Set, TYPE_CHECKING

from scenedetect import FrameTimecode

from gif_pipeline.chat_config import TagType
from gif_pipeline.database import Database, MenuData
from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.helpers.menus.edit_gnostic_tag_values_menu import EditGnosticTagValuesMenu
from gif_pipeline.helpers.menus.edit_single_tag_values_menu import EditSingleTagValuesMenu
from gif_pipeline.helpers.menus.edit_text_tag_values_menu import EditTextTagValuesMenu
from gif_pipeline.helpers.menus.split_scenes_confirmation_menu import SplitScenesConfirmationMenu
from gif_pipeline.helpers.menus.delete_menu import DeleteMenu
from gif_pipeline.helpers.menus.send_confirmation_menu import SendConfirmationMenu
from gif_pipeline.helpers.menus.edit_tag_values_menu import EditTagValuesMenu
from gif_pipeline.helpers.menus.tag_select_menu import TagSelectMenu
from gif_pipeline.helpers.menus.check_tags_menu import CheckTagsMenu
from gif_pipeline.helpers.menus.destination_menu import DestinationMenu
from gif_pipeline.helpers.menus.not_gif_confirmation_menu import NotGifConfirmationMenu
from gif_pipeline.helpers.scene_split_helper import SceneSplitHelper
from gif_pipeline.helpers.send_helper import GifSendHelper
from gif_pipeline.menu_cache import SentMenu
from gif_pipeline.message import Message
from gif_pipeline.tag_manager import TagManager
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient

if TYPE_CHECKING:
    from gif_pipeline.pipeline import Pipeline


class MenuHelper(Helper):

    def __init__(
            self,
            database: Database,
            client: TelegramClient,
            worker: TaskWorker,
            pipeline: 'Pipeline',
            tag_manager: TagManager,
    ):
        super().__init__(database, client, worker)
        # Cache of message ID the menu is replying to, to the menu
        self.pipeline = pipeline
        self.menu_cache = pipeline.menu_cache
        self.tag_manager = tag_manager

    def is_priority(self, chat: Chat, message: Message) -> bool:
        if not message.message_data.reply_to:
            return False
        # Get the menu this message is replying to
        menu = self.menu_cache.get_menu_by_message_id(chat.chat_data.chat_id, message.message_data.reply_to)
        if not menu:
            return False
        return menu.menu.capture_text()

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        if not message.message_data.reply_to:
            return None
        # Get the menu this message is replying to
        menu = self.menu_cache.get_menu_by_message_id(chat.chat_data.chat_id, message.message_data.reply_to)
        if not menu:
            return None
        if menu.menu.capture_text():
            return await menu.menu.handle_text(message.text)
        return None

    async def on_callback_query(
            self,
            callback_query: bytes,
            menu: SentMenu
    ) -> Optional[List[Message]]:
        # Prevent double clicking menus
        menu.clicked = True
        resp = await menu.menu.handle_callback_query(callback_query)
        return resp

    def refresh_from_database(self) -> None:
        list_menus = self.database.list_menus()
        for menu_data in list_menus:
            sent_menu = self.create_menu(menu_data)
            self.menu_cache.add_menu(sent_menu)

    def create_menu(
            self,
            menu_data: MenuData
    ) -> SentMenu:
        menu_json = json.loads(menu_data.menu_json_str)
        chat = self.pipeline.chat_by_id(menu_data.chat_id)
        menu_msg = chat.message_by_id(menu_data.menu_msg_id)
        video_msg = chat.message_by_id(menu_data.video_msg_id)
        clicked = menu_data.clicked
        if menu_data.menu_type == CheckTagsMenu.json_name():
            send_helper = self.pipeline.helpers[GifSendHelper.__name__]
            menu = CheckTagsMenu.from_json(menu_json, self, chat, video_msg, send_helper)
            return SentMenu(menu, menu_msg, clicked)
        if menu_data.menu_type == DeleteMenu.json_name():
            menu = DeleteMenu.from_json(menu_json, self, chat, video_msg)
            return SentMenu(menu, menu_msg, clicked)
        if menu_data.menu_type == DestinationMenu.json_name():
            send_helper = self.pipeline.helpers[GifSendHelper.__name__]
            channels = self.pipeline.channels
            menu = DestinationMenu.from_json(menu_json, self, chat, video_msg, send_helper, channels, self.tag_manager)
            return SentMenu(menu, menu_msg, clicked)
        if menu_data.menu_type in [
            EditSingleTagValuesMenu.json_name(),
            EditTextTagValuesMenu.json_name(),
            EditTagValuesMenu.json_name(),
            EditGnosticTagValuesMenu.json_name()
        ]:
            cls = {
                EditSingleTagValuesMenu.json_name(): EditSingleTagValuesMenu,
                EditTextTagValuesMenu.json_name(): EditTextTagValuesMenu,
                EditTagValuesMenu.json_name(): EditTagValuesMenu,
                EditGnosticTagValuesMenu.json_name(): EditGnosticTagValuesMenu
            }.get(menu_data.menu_type)
            send_helper = self.pipeline.helpers[GifSendHelper.__name__]
            channels = self.pipeline.channels
            tag_manager = self.tag_manager
            menu = cls.from_json(menu_json, self, chat, video_msg, send_helper, channels, tag_manager)
            return SentMenu(menu, menu_msg, clicked)
        if menu_data.menu_type == NotGifConfirmationMenu.json_name():
            send_helper = self.pipeline.helpers[GifSendHelper.__name__]
            menu = NotGifConfirmationMenu.from_json(menu_json, self, chat, video_msg, send_helper)
            return SentMenu(menu, menu_msg, clicked)
        if menu_data.menu_type == SendConfirmationMenu.json_name():
            send_helper = self.pipeline.helpers[GifSendHelper.__name__]
            channels = self.pipeline.channels
            menu = SendConfirmationMenu.from_json(menu_json, self, chat, video_msg, send_helper, channels)
            return SentMenu(menu, menu_msg, clicked)
        if menu_data.menu_type == SplitScenesConfirmationMenu.json_name():
            split_helper = self.pipeline.helpers[SceneSplitHelper.__name__]
            menu = SplitScenesConfirmationMenu.from_json(menu_json, self, chat, video_msg, split_helper)
            return SentMenu(menu, menu_msg, clicked)
        if menu_data.menu_type == TagSelectMenu.json_name():
            send_helper = self.pipeline.helpers[GifSendHelper.__name__]
            channels = self.pipeline.channels
            menu = TagSelectMenu.from_json(menu_json, self, chat, video_msg, send_helper, channels)
            return SentMenu(menu, menu_msg, clicked)
        return None

    async def delete_menu_for_video(self, video: Message) -> None:
        menu = self.menu_cache.get_menu_by_video(video)
        if menu:
            await self.client.delete_message(menu.msg.message_data)
            menu.msg.delete(self.database)
            self.menu_cache.remove_menu_by_video(video)

    async def send_not_gif_warning_menu(
            self,
            chat: Chat,
            cmd: Message,
            video: Message,
            send_helper: GifSendHelper,
            dest_str: str
    ) -> List[Message]:
        menu = NotGifConfirmationMenu(self, chat, cmd, video, send_helper, dest_str)
        menu_msg = await menu.send()
        return [menu_msg]

    async def destination_menu(
            self,
            chat: Chat,
            cmd: Message,
            video: Message,
            send_helper: GifSendHelper,
            channels: List[Channel]
    ) -> List[Message]:
        menu = DestinationMenu(self, chat, cmd, video, send_helper, channels, self.tag_manager)
        menu_msg = await menu.send()
        return [menu_msg]

    async def additional_tags_menu(
            self,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Channel,
            missing_tags: Set[str]
    ):
        menu = CheckTagsMenu(self, chat, cmd_msg, video, send_helper, destination, missing_tags)
        menu_msg = await menu.send()
        return [menu_msg]

    async def edit_tag_select(
            self,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Channel,
            missing_tags: Set[str]
    ):
        menu = TagSelectMenu(self, chat, cmd_msg, video, send_helper, destination, missing_tags)
        menu_msg = await menu.send()
        return [menu_msg]

    async def edit_tag_values(
            self,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Channel,
            tag_name: str
    ):
        menu_class = {
            TagType.NORMAL: EditTagValuesMenu,
            TagType.SINGLE: EditSingleTagValuesMenu,
            TagType.TEXT: EditTextTagValuesMenu,
            TagType.GNOSTIC: EditGnosticTagValuesMenu
        }[destination.config.tags[tag_name].type]
        menu = menu_class(self, chat, cmd_msg, video, send_helper, destination, self.tag_manager, tag_name)
        menu_msg = await menu.send()
        return [menu_msg]

    async def confirmation_menu(
            self,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Channel,
    ) -> List[Message]:
        menu = SendConfirmationMenu(self, chat, cmd_msg, video, send_helper, destination)
        menu_msg = await menu.send()
        return [menu_msg]

    async def after_send_delete_menu(
            self,
            chat: Chat,
            cmd: Message,
            video: Message,
            text: str,
    ) -> Optional[Message]:
        admin_ids = await self.client.list_authorized_to_delete(chat.chat_data)
        if cmd.message_data.sender_id not in admin_ids:
            await self.delete_menu_for_video(video)
            return None
        menu = DeleteMenu(self, chat, cmd, video, text)
        message = await menu.send()
        return message

    async def split_scenes_confirmation(
            self,
            chat: Chat,
            cmd: Message,
            video: Message,
            threshold: int,
            scene_list: List[Tuple[FrameTimecode, FrameTimecode]],
            split_helper: SceneSplitHelper
    ) -> Message:
        menu = SplitScenesConfirmationMenu(self, chat, cmd, video, threshold, scene_list, split_helper)
        message = await menu.send()
        return message
