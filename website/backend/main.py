import json
import os.path
from typing import Optional, Union

import flask
from flask import Flask, Response

from gif_pipeline.chat_config import ChannelConfig
from gif_pipeline.chat_data import ChannelData
from gif_pipeline.database import Database
from gif_pipeline.pipeline import PipelineConfig


ROOT_DIR = f"{os.path.dirname(__file__)}/../../live/2023-07-25/"
app = Flask(__name__)
with open(f"{ROOT_DIR}/config.json", "r") as c:
    CONF = json.load(c)
pipeline_conf = PipelineConfig(CONF)
database = Database(filename=f"{ROOT_DIR}/pipeline.sqlite")


def _get_chat_data_for_handle(handle: Union[str, int]) -> Optional[ChannelData]:
    for channel_data in database.list_channels():
        if channel_data.matches_handle(handle):
            return channel_data


def _get_chat_config_for_handle(handle: Union[str, int]) -> Optional[ChannelConfig]:
    for channel_config in pipeline_conf.channels:
        if channel_config.handle == handle:
            return channel_config


@app.route("/chats/<chat_id>.json")
def api_channel_tags(chat_id: str) -> Response:
    chat_data = _get_chat_data_for_handle(chat_id)
    chat_config = _get_chat_config_for_handle(chat_id)
    if chat_data is None or chat_config is None or not chat_config.website_config.enabled:
        return flask.jsonify({"error": "Chat not found"}), 404
    messages = database.list_messages_for_chat(chat_data)
    message_data = []
    for message in messages:
        tags = database.get_tags_for_message(message)
        message_data.append({
            "msg_id": message.message_id,
            "chat_id": message.chat_id,
            "tags": [
                {
                    "name": tag.tag_name,
                    "value": tag.tag_value,
                } for tag in tags
            ]
        })
    return flask.jsonify(message_data)


@app.route("/chats.json")
def api_chat_list() -> Response:
    channels = [channel for channel in pipeline_conf.channels if channel.website_config.publicly_listed]
    channel_data = []
    for channel in channels:
        tags_config = None
        if channel.tags:
            tags_config = {
                name: {
                    "type": config.type.value,
                } for name, config in channel.tags.items()
            }
        channel_data.append({
            "handle": channel.handle,
            "read_only": channel.read_only,
            "tag_config": tags_config,
        })
    return {
        "channels": channel_data,
    }


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=3000)
