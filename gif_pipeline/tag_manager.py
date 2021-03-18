from typing import List, Optional, Union

from gif_pipeline.chat import Channel, WorkshopGroup, Chat
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

    def get_values_for_tag(self, tag_name: str, destination: Channel) -> List[str]:
        return self.database.list_tag_values(tag_name, destination.chat_data)
