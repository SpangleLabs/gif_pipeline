import json

import flask
from flask import Flask, Response

from gif_pipeline.database import Database
from gif_pipeline.pipeline import PipelineConfig

app = Flask(__name__)
with open("../../config.json", "r") as c:
    CONF = json.load(c)
pipeline_conf = PipelineConfig(CONF)
database = Database()


@app.route("/tags/<chat_id>.json")
def api_channel_tags(chat_id: str) -> Response:
    chat_data = database.list_channels()
    found_chat = None
    for chat_datum in chat_data:
        if chat_datum.matches_handle(chat_id):
            found_chat = chat_datum
            break
    if found_chat is None:
        return flask.jsonify({"error": "Chat not found"}), 404
        return

    messages = []
    # TODO: database.get_tags_for_message(self.message_data)
    pass  # TODO


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
