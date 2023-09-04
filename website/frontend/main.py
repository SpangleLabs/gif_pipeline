import dataclasses
import json
from typing import Dict, List, Set, Optional

import flask
import requests
from flask import Flask, Response


app = Flask(__name__, template_folder="templates/")

API_ROOT = "http://localhost:47507/"


def link_text(link: ParseResult) -> str:
    hostname = parsed.hostname.lower()
    split_path = parsed.path.lstrip("/").split("/")
    if hostname in ["twitter.com", "www.twitter.com", "vxtwitter.com", "fxtwitter.com", "x.com"]:
        if split_path:
            username = split_path[0]
            return f"Twitter: {username}"
        return "Twitter link"
    if hostname in ["youtube.com", "youtu.be", "www.youtube.com"]:
        return f"Youtube link"
    if hostname in ["www.reddit.com", "reddit.com", "redd.it"]:
        if len(split_path) >= 2 and split_path[0] == "r":
            subreddit = split_path[1]
            return f"Reddit: r/{subreddit}"
        return "Reddit link"
    if hostname in ["tiktok.com", "www.tiktok.com"]:
        if split_path:
            username = split_path[0]
            return f"Tiktok: {username}"
        return "Tiktok link"
    if hostname in ["t.me"]:
        if split_path:
            username = split_path[0]
            if username == "c":
                return "Private telegram channel"
            return f"Telegram: @{username}"
        return "Telegram link"
    return "Link"


def format_tag_value(tag_value: str) -> str:
    if not tag_value.lower().startswith("http"):
        return tag_value
    parsed = urlparse(tag_value)
    if parsed.scheme.lower() not in ["http", "https"]:
        return tag_value
    return f"<a href=\"{tag_value}\">{link_text(parsed)}</a>"


@dataclasses.dataclass
class ChannelTag:
    name: str
    tag_type: str
    in_config: bool
    message_ids: Set = dataclasses.field(default_factory=set)
    tag_values: Set = dataclasses.field(default_factory=set)

    def tag_names(self) -> List[str]:
        if self.tag_type == "gnostic":
            return [f"{self.name}__rejected", f"{self.name}__confirmed"]
        return [self.name]

    def matches_tag(self, tag_name: str) -> bool:
        return tag_name in self.tag_names()

    @property
    def message_count(self) -> int:
        return len(self.message_ids)

    def add_message(self, msg_id: int, tag_value: str) -> None:
        self.message_ids.add(msg_id)
        self.tag_values.add(tag_value)


class ChannelTags:
    def __init__(self, chat_data: Dict) -> None:
        self.chat_data = chat_data
        self.tag_config = chat_data["config"]["tag_config"] or {}
        self._channel_tags: Optional[List[ChannelTag]] = None

    def list_channel_tags(self) -> List[ChannelTag]:
        if self._channel_tags:
            return self._channel_tags
        channel_tags = []
        tags_by_name = {}
        # Go through configured tags
        for tag_name, tag_config in self.tag_config.items():
            channel_tag = ChannelTag(
                tag_name,
                tag_config["type"],
                True,
            )
            channel_tags.append(channel_tag)
            for name in channel_tag.tag_names():
                tags_by_name[name] = channel_tag
        # Go through messages looking for unconfigured tags
        for msg in self.chat_data["messages"]:
            for tag_entry in msg["tags"]:
                tag_name = tag_entry["name"]
                if tag_name in tags_by_name:
                    tags_by_name[tag_name].add_message(msg["msg_id"], tag_entry["value"])
                else:
                    channel_tag = ChannelTag(
                        tag_name,
                        "unknown",
                        False,
                    )
                    channel_tags.append(channel_tag)
                    tags_by_name[tag_name] = channel_tag
                    channel_tag.add_message(msg["msg_id"], tag_entry["value"])
        self._channel_tags = channel_tags
        return channel_tags

    def table_dict_for_msg(self, msg_data: Dict) -> Dict[str, List[str]]:
        tags_dict = {}
        for tag_entry in msg_data["tags"]:
            tag_name = tag_entry["name"]
            tag_value = tag_entry["value"]
            # Clean up gnostic tags
            if tag_name.endswith("__rejected"):
                continue
            tag_name = tag_name.removesuffix("__confirmed")
            # Note tag value for name
            if tag_name not in tags_dict:
                tags_dict[tag_name] = []
            tags_dict[tag_name].append(tag_value)
        # Sort dict
        channel_tags = [tag.name for tag in self.list_channel_tags()]
        tags_dict = dict(sorted(tags_dict.items(), key=lambda k: channel_tags.index(k[0])))
        return tags_dict

    def tag_names_in_config(self) -> List[str]:
        channel_tags = self.list_channel_tags()
        return [
            channel_tag.name for channel_tag in channel_tags if channel_tag.in_config
        ]


@app.route("/<chat_id>")
def view_channel_page(chat_id: str) -> Response:
    data = requests.get(f"{API_ROOT}/chats/{chat_id}.json").json()
    if "error" in data:
        return Response(f"Error: {data['error']}", 500)
    chat_title = data["data"]["title"]
    handle = data["config"]["handle"]
    channel_tag_data = ChannelTags(data)
    return Response(flask.render_template(
        "chat_page.html.jinja2",
        chat_title=chat_title,
        handle=handle,
        channel_tag_data=channel_tag_data,
        message_list=data["messages"][::-1],
        format_tag_value=format_tag_value,
    ))


@app.route("/")
def api_chat_list() -> Response:
    data = requests.get(f"{API_ROOT}/chats.json").json()
    response = "<html><head><title>Gif pipeline channel listing</title></head><body>Available channels:<ul>"
    for channel in data["channels"]:
        handle = channel["config"]["handle"]
        title = channel["data"]["title"]
        response += f'<li><a href="{handle}">{title}</a></li>'
    response += "</ul></body></html>"
    return flask.make_response(response)


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=3100)
