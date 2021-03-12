from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict, Optional

from gif_pipeline.chat import Channel, WorkshopGroup, Chat
from gif_pipeline.chat_config import ChatConfig
from gif_pipeline.message import Message


@dataclass
class TagEntry:
    tag_name: str
    tag_value: str


class VideoTags:
    source = "source"

    def __init__(self, tags: Optional[Dict[str, List[str]]] = None):
        self.tags = tags or {}

    def add_tag_value(self, tag_name: str, tag_value: str) -> None:
        if tag_name not in self.tags:
            self.tags[tag_name] = []
        self.tags[tag_name].append(tag_value)

    @classmethod
    def from_database(cls, tag_data: List[TagEntry]) -> 'VideoTags':
        tags_dict = defaultdict(lambda: [])
        for tag in tag_data:
            tags_dict[tag.tag_name].append(tag.tag_value)
        return VideoTags(
            tags_dict
        )

    def to_entries(self) -> List[TagEntry]:
        return [
            TagEntry(key, value)
            for key, values in self.tags.items()
            for value in values
        ]


class TagManager:
    def __init__(self, channels: List[Channel], workshops: List[WorkshopGroup]):
        self.channels = channels
        self.workshops = workshops

    def get_message_for_link(self, link: str) -> Optional[Message]:
        link_split = link.strip("/").split("/")
        if len(link_split) < 2:
            return None
        message_id = int(link_split[-1])
        handle = link_split[-2]
        all_chats: List[Chat] = [*self.channels, *self.workshops]
        chat_config = ChatConfig(handle)
        for chat in all_chats:
            if chat.chat_data.matches_config(chat_config):
                return chat.message_by_id(message_id)
        return None
