import base64
import json
import os.path
from typing import Optional, Union, Dict

import flask
from flask import Flask, Response

from gif_pipeline.chat_config import ChannelConfig
from gif_pipeline.chat_data import ChannelData
from gif_pipeline.database import Database
from gif_pipeline.pipeline import PipelineConfig


ROOT_DIR = f"{os.path.dirname(__file__)}/../../"
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


def _config_to_json(chat_config: ChannelConfig) -> Dict:
    tags_config = None
    if chat_config.tags:
        tags_config = {
            name: {
                "type": config.type.value,
            } for name, config in chat_config.tags.items()
        }
    return {
        "handle": chat_config.handle,
        "read_only": chat_config.read_only,
        "tag_config": tags_config,
    }


def _data_to_json(chat_data: ChannelData) -> Dict:
    return {
        "chat_id": chat_data.chat_id,
        "username": chat_data.username,
        "title": chat_data.title,
    }


@app.route("/chats/<chat_id>.json")
def api_channel_tags(chat_id: str) -> Response:
    chat_data = _get_chat_data_for_handle(chat_id)
    chat_config = _get_chat_config_for_handle(chat_id)
    if chat_data is None or chat_config is None or not chat_config.website_config.enabled:
        resp = flask.jsonify({"error": "Chat not found"})
        resp.status = 404
        return resp
    messages = database.list_messages_for_chat(chat_data)
    message_list = []
    all_tags = database.get_tags_for_chat(chat_data)
    for message in messages:
        if not message.has_video:
            continue
        tags = all_tags.get(message.message_id, [])
        thumbnail_str = None
        thumbnail = database.get_thumbnail_data(message)
        if thumbnail:
            thumbnail_str = base64.b64encode(thumbnail).decode()
        message_list.append({
            "msg_id": message.message_id,
            "chat_id": message.chat_id,
            "tags": [
                {
                    "name": tag.tag_name,
                    "value": tag.tag_value,
                } for tag in tags
            ],
            "thumbnail": thumbnail_str
        })
    return flask.jsonify({
        "config": _config_to_json(chat_config),
        "data": _data_to_json(chat_data),
        "messages": message_list,
    })


@app.route("/chats.json")
def api_chat_list() -> Response:
    channel_configs = [channel for channel in pipeline_conf.channels if channel.website_config.publicly_listed]
    channel_list = []
    for channel_config in channel_configs:
        channel_data = _get_chat_data_for_handle(channel_config.handle)
        channel_list.append({
            "config": _config_to_json(channel_config),
            "data": _data_to_json(channel_data),
        })
    return flask.jsonify({
        "channels": channel_list,
    })


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=3000)
