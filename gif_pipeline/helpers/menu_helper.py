from typing import Optional, List, Tuple, Set

from scenedetect import FrameTimecode

from gif_pipeline.chat_config import TagType
from gif_pipeline.database import Database
from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.helpers.menus.menu import NotGifConfirmationMenu, DestinationMenu, CheckTagsMenu, EditTagSelectMenu, \
    EditTagValuesMenu, SendConfirmationMenu, DeleteMenu, SplitScenesConfirmationMenu
from gif_pipeline.helpers.scene_split_helper import SceneSplitHelper
from gif_pipeline.helpers.send_helper import GifSendHelper
from gif_pipeline.menu_cache import MenuCache, SentMenu
from gif_pipeline.message import Message
from gif_pipeline.tag_manager import TagManager
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient


class MenuHelper(Helper):

    def __init__(
            self,
            database: Database,
            client: TelegramClient,
            worker: TaskWorker,
            menu_cache: MenuCache,
            tag_manager: TagManager,
    ):
        super().__init__(database, client, worker)
        # Cache of message ID the menu is replying to, to the menu
        self.menu_cache = menu_cache
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
            channels: List[Channel],
            current_folder: Optional[str] = None
    ) -> List[Message]:
        menu = DestinationMenu(self, chat, cmd, video, send_helper, channels, current_folder)
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
        menu = EditTagSelectMenu(self, chat, cmd_msg, video, send_helper, destination, missing_tags)
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
            TagType.SINGLE: EditTagValuesMenu,
            TagType.TEXT: EditTagValuesMenu,
            TagType.GNOSTIC: EditTagValuesMenu
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


