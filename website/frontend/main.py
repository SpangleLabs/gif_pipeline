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
    response = f"""<html>
    <head><title>{chat_title}</title></head>
    <body>
    <h1>{chat_title}</h1>
    <b>Handle:</b> {handle}</br>
    <b>Telegram link:</b> https://t.me/{handle}</br>
    <b>Tag config:</b></br>
    <table><tr><th>Name</th><th>Type</th><th>Other config</th></tr>"""
    for tag_name, tag_config in data["config"]["tag_config"].items():
        tag_type = tag_config.pop("type")
        other_config = f"<pre>{json.dumps(tag_config, indent=2)}</pre>"
        if not tag_config:
            other_config = "-"
        response += f"""<tr><td>{tag_name}</td><td>{tag_type}</td><td>{other_config}</td></tr>"""
    response += f"""</table>
    <h2>Messages:</h2>"""
    for message in data["messages"]:
        msg_id = message["msg_id"]
        tags = json.dumps(message["tags"])
        tags_dict = {}
        for tag_entry in message["tags"]:
            if tag_entry["name"] not in tags_dict:
                tags_dict[tag_entry["name"]] = []
            tags_dict[tag_entry["name"]].append(tag_entry["value"])
        response += "<table>"
        response += f"""<tr><td colspan=2><script async src="https://telegram.org/js/telegram-widget.js?22" data-telegram-post="{handle}/{msg_id}" data-width="100%"></script></td></tr>"""
        for tag_name, tag_values in tags_dict.items():
            if tag_name.endswith("__rejected"):
                continue
            display_name = tag_name.removesuffix("__confirmed")
            name_cell = f"<td>{display_name}</td>"
            if display_name in data["config"]["tag_config"]:
                name_cell = f"<td><b>{display_name}</b></td>"
            response += f"<tr>{name_cell}<td>{', '.join(tag_values)}</td></tr>"
        response += "</table>"
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
