from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict, Optional


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
            for key, values in self.tags
            for value in values
        ]
