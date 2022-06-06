import string
from collections import defaultdict
from typing import TYPE_CHECKING

from jinja2 import BaseLoader, Environment

if TYPE_CHECKING:
    from gif_pipeline.video_tags import VideoTags


class TextFormatter:
    def __init__(self, text: str):
        self.text = text

    def format(self, tags: "VideoTags") -> str:
        if self.text == "":
            return ""
        tag_dict = defaultdict(list)
        for tag_name in tags.list_tag_names():
            tag_dict[tag_name] = list(tags.list_values_for_tag(tag_name))
        template = Environment(loader=BaseLoader()).from_string(self.text)
        return template.render(tags=tag_dict)
