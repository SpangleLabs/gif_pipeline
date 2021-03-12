from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, Dict, List, Set


@dataclass
class TagEntry:
    tag_name: str
    tag_value: str


class VideoTags:
    source = "source"

    def __init__(self, tags: Optional[Dict[str, Set[str]]] = None):
        self.tags = tags or {}

    def add_tag_value(self, tag_name: str, tag_value: str) -> None:
        if tag_name not in self.tags:
            self.tags[tag_name] = set()
        self.tags[tag_name].add(tag_value)

    def merge_with(self, other: 'VideoTags') -> None:
        for entry in other.to_entries():
            self.add_tag_value(entry.tag_name, entry.tag_value)

    def merge_all(self, others: List['VideoTags']) -> None:
        for other in others:
            self.merge_with(other)

    @classmethod
    def from_database(cls, tag_data: List[TagEntry]) -> 'VideoTags':
        tags_dict = defaultdict(lambda: set())
        for tag in tag_data:
            tags_dict[tag.tag_name].add(tag.tag_value)
        return VideoTags(
            tags_dict
        )

    def to_entries(self) -> List[TagEntry]:
        return [
            TagEntry(key, value)
            for key, values in self.tags.items()
            for value in values
        ]
