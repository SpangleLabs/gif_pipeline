import json

import flask
import requests
from flask import Flask, Response

app = Flask(__name__)

API_ROOT = "http://localhost:3000/"


@app.route("/<chat_id>")
def view_channel_page(chat_id: str) -> Response:
    data = requests.get(f"{API_ROOT}/chats/{chat_id}.json").json()
    chat_title = data["data"]["title"]
    handle = data["config"]["handle"]
    tag_config_str = json.dumps(data["config"]["tags"])
    response = f"""<html>
    <head><title>{chat_title}<title></head>
    <body>
    <h1>{chat_title}</h1>
    <b>Handle:</b> {handle}</br>
    <b>Telegram link:</b> https://t.me/{handle}</br>
    <b>Tag config:</b></br>
    <pre>{tag_config_str}</pre>
    <h2>Messages:</h2>"""
    for message in data["messages"]:
        msg_id = message["msg_id"]
        tags = json.dumps(message["tags"])
        response += f"""<script async src="https://telegram.org/js/telegram-widget.js?22" data-telegram-post="{handle}/{msg_id}" data-width="100%"></script>"""
        response += f"<pre>{tags}</pre>"
    response += "</body></html>"
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
