from typing import Set
from collections import Counter

from gif_pipeline.chat import Channel, Chat
from gif_pipeline.chat_config import TagType
from gif_pipeline.database import Database
from gif_pipeline.message import Message
from gif_pipeline.video_tags import gnostic_tag_name_positive, gnostic_tag_name_negative


class TagManager:
    def __init__(self, database: Database):
        self.database = database

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
