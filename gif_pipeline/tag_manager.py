from collections import Counter
from typing import List, Optional, Set, Union, TYPE_CHECKING

from gif_pipeline.chat import Channel, Chat, WorkshopGroup
from gif_pipeline.chat_config import TagType
from gif_pipeline.video_tags import gnostic_tag_name_negative, gnostic_tag_name_positive

if TYPE_CHECKING:
    from gif_pipeline.database import Database
    from gif_pipeline.message import Message


class TagManager:
    def __init__(self, channels: List[Channel], workshops: List[WorkshopGroup], database: Database):
        self.channels = channels
        self.workshops = workshops
        self.database = database

    def get_message_for_ids(self, handle: Union[int, str], message_id: int) -> Optional[Message]:
        all_chats: List[Chat] = [*self.channels, *self.workshops]
        for chat in all_chats:
            if chat.chat_data.matches_handle(str(handle)):
                return chat.message_by_id(message_id)
        return None

    def get_message_for_link(self, link: str) -> Optional[Message]:
        link_split = link.strip("/").split("/")
        if len(link_split) < 2:
            return None
        message_id = int(link_split[-1])
        handle = link_split[-2]
        return self.get_message_for_ids(handle, message_id)

    def get_values_for_tag(self, tag_name: str, chats: [Chat]) -> Set[str]:
        chat_ids = []
        for chat in chats:
            chat_ids.append(chat.chat_data.chat_id)
            if isinstance(chat, Channel):
                if chat.queue:
                    chat_ids.append(chat.queue.chat_data.chat_id)
        return set(self.database.list_tag_values(tag_name, chat_ids))

    def missing_tags_for_video(self, video: Message, destination: Channel, chat: Chat) -> Set[str]:
        tags = video.tags(self.database)
        dest_tags = destination.config.tags
        # Handle gnostic tags in all values dict.
        chats = [destination, chat]
        all_values_dict = {}
        for tag_name, tag_conf in dest_tags.items():
            if tag_conf.type == TagType.GNOSTIC:
                tag_name_pos = gnostic_tag_name_positive(tag_name)
                tag_name_neg = gnostic_tag_name_negative(tag_name)
                all_values_dict[tag_name_pos] = self.get_values_for_tag(tag_name_pos, chats)
                all_values_dict[tag_name_neg] = self.get_values_for_tag(tag_name_neg, chats)
            else:
                all_values_dict[tag_name] = self.get_values_for_tag(tag_name, chats)
        return tags.incomplete_tags(dest_tags, all_values_dict)

    def tag_value_rates_for_chat(self, dest: Channel, tag_name: str) -> Counter:
        counter = Counter()
        tag_config = dest.config.tags[tag_name]
        tag_key = tag_name
        if tag_config.type == TagType.GNOSTIC:
            tag_key = gnostic_tag_name_positive(tag_name)
        for video in dest.messages:
            tags = video.tags(self.database)
            values = tags.list_values_for_tag(tag_key)
            counter.update(values)
        return counter
