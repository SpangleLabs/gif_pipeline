from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, Dict, List, Set

from gif_pipeline.chat_config import TagConfig, TagType


@dataclass
class TagEntry:
    tag_name: str
    tag_value: str


class VideoTags:
    source = "source"

    def __init__(self, tags: Optional[Dict[str, Set[str]]] = None):
        self._tags = tags or {}

    def add_tag_value(self, tag_name: str, tag_value: str) -> None:
        if tag_name not in self._tags:
            self._tags[tag_name] = set()
        self._tags[tag_name].add(tag_value)

    def toggle_tag_value(self, tag_name: str, tag_value: str) -> None:
        if tag_name not in self._tags:
            self._tags[tag_name] = set()
        self._tags[tag_name] ^= {tag_value}

    def merge_with(self, other: 'VideoTags') -> None:
        for entry in other.to_entries():
            self.add_tag_value(entry.tag_name, entry.tag_value)

    def merge_all(self, others: List['VideoTags']) -> None:
        for other in others:
            self.merge_with(other)

    def remove_all_values_for_tag(self, tag_name: str) -> None:
        if tag_name in self._tags:
            del self._tags

    def remove_tag_value(self, tag_name: str, tag_value: str) -> None:
        if tag_name not in self._tags:
            return
        self._tags[tag_name].discard(tag_value)

    def list_tag_names(self) -> Set[str]:
        return set(self._tags.keys())

    def list_values_for_tag(self, tag_name: str) -> Set[str]:
        return self._tags.get(tag_name, set())

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
            for key, values in self._tags.items()
            for value in values
        ]

    def incomplete_tags(self, dest_tags: Dict[str, TagConfig], all_values_dict: Dict[str, Set[str]]) -> Set[str]:
        return {
            tag_name
            for tag_name, tag_config in dest_tags.items()
            if self.is_tag_complete(tag_name, tag_config, all_values_dict[tag_name])
        }

    def is_tag_complete(self, tag_name: str, tag_config: TagConfig, all_values: Set[str]) -> bool:
        if not self._tags.get(tag_name, set()):
            return False
        if tag_config.type == TagType.GNOSTIC:
            pos_values = self.list_values_for_tag(f"{tag_name}__confirmed")
            neg_values = self.list_values_for_tag(f"{tag_name}__rejected")
            total_values = pos_values.union(neg_values)
            return not bool(all_values - total_values)
        return True
