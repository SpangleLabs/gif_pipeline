import dataclasses
import json
from typing import Dict, List, Set, Optional

import flask
import requests
from flask import Flask, Response


app = Flask(__name__)

API_ROOT = "http://localhost:3000/"


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
        self.tag_config = chat_data["config"]["tag_config"]
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
            if tag_name not in tags_dict:
                tags_dict[tag_name] = []
            tags_dict[tag_name].append(tag_value)
        return tags_dict


@app.route("/<chat_id>")
def view_channel_page(chat_id: str) -> Response:
    data = requests.get(f"{API_ROOT}/chats/{chat_id}.json").json()
    chat_title = data["data"]["title"]
    handle = data["config"]["handle"]
    channel_tag_data = ChannelTags(data)
    response = f"""<html>
    <head>
    <title>{chat_title}</title>
    <style>
    th {{
        background-color: #FDFD96;
    }}
    table {{
        border: 2px solid black;
        border-collapse: collapse;
        margin: 10px;
    }}
    td {{
        border: 1px solid grey;
    }}
    body {{
        font-family: sans-serif;
    }}
    </style>
    </head>
    <body>
    <h1>{chat_title}</h1>
    <b>Handle:</b> {handle}</br>
    <b>Telegram link:</b> https://t.me/{handle}</br>
    <b>Tag config:</b></br>
    <table><tr><th>Name</th><th>Type</th><th>In config?</th><th>Message count</th></tr>"""
    for channel_tag in channel_tag_data.list_channel_tags():
        official_str = "Y" if channel_tag.in_config else "N"
        name_str = channel_tag.name
        if channel_tag.in_config:
            name_str = f"<b>{channel_tag.name}</b>"
        response += f"""<tr><td>{name_str}</td><td>{channel_tag.tag_type}</td><td>{official_str}</td><td>{channel_tag.message_count}</tr>"""
    response += f"""</table>
    <h2>Messages:</h2><div id="messages">"""
    for message in data["messages"][::-1][:10]:
        msg_id = message["msg_id"]
        response += "<table>"
        response += f"""<tr><td colspan=2><script async src="https://telegram.org/js/telegram-widget.js?22" data-telegram-post="{handle}/{msg_id}" data-width="100%"></script></td></tr>"""
        tags_dict = channel_tag_data.table_dict_for_msg(message)
        for tag_name, tag_values in tags_dict.items():
            if tag_name.endswith("__rejected"):
                continue
            display_name = tag_name.removesuffix("__confirmed")
            name_cell = f"<td>{display_name}</td>"
            if display_name in data["config"]["tag_config"]:
                name_cell = f"<td><b>{display_name}</b></td>"
            response += f"<tr>{name_cell}<td>{', '.join(tag_values)}</td></tr>"
        response += "</table>"
    response += "</div></body></html>"
    return flask.make_response(response)


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
