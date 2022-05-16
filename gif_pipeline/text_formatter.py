import string
from collections import defaultdict

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gif_pipeline.video_tags import VideoTags


class TextFormatter:
    def __init__(self, text: str):
        self.text = text

    def format(self, tags: "VideoTags") -> str:
        tag_dict = defaultdict(str)
        for tag_name in tags.list_tag_names():
            tag_dict[tag_name] = ", ".join(tags.list_values_for_tag(tag_name))
        return string.Formatter().format(self.text, tags=tag_dict)
