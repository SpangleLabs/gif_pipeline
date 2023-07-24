import json

from flask import Flask, Response

from gif_pipeline.pipeline import PipelineConfig

app = Flask(__name__)
with open("config.json", "r") as c:
    CONF = json.load(c)
pipeline_conf = PipelineConfig(CONF)


@app.route("/tags/<chat_id>.json")
def api_channel_tags(chat_id: str) -> flask.Response:
    # TODO: database.get_tags_for_message(self.message_data)
    pass  # TODO


@app.route("/chats.json")
def api_chat_list() -> flask.Response:
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
