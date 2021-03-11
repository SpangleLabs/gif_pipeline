from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict

from gif_pipeline.message import Message


@dataclass
class TagEntry:
    tag_name: str
    tag_value: str


class VideoTags:
    def __init__(self, video: Message, tags: Dict[str, List[str]]):
        self.video = video
        self.tags = tags

    @classmethod
    def from_database(cls, video: Message, tag_data: List[TagEntry]) -> 'VideoTags':
        tags_dict = defaultdict(lambda: [])
        for tag in tag_data:
            tags_dict[tag.tag_name].append(tag.tag_value)
        return VideoTags(
            video,
            tags_dict
        )

    def to_entries(self) -> List[TagEntry]:
        return [
            TagEntry(key, value)
            for key, values in self.tags
            for value in values
        ]
