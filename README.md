# gif_pipeline
A telegram pipeline helper, to help organise, prepare, and send videos for gif channels.
It also handles tagging, and can post videos to twitter.

## Install and requirements
Installing should be as easy as:
`poetry install`

The application will then install and automatically update yt-dlp while running.

To run, use the command:
`poetry run python ./main.py`

## Configuration
Configuration is done via the `config.json` file. This file is updated manually only. The application state is then stored in `pipeline.sqlite`

At the base level of the config file are these keys:
- `api_id`: `int`, the telegram client API key, as obtained from https://my.telegram.org
- `api_hash`: `str`, the api hash to login to the user's telegram account who is running the application. This is required to allow the bot access to extra information about channel state not allowed by bots.
- `pipeline_bot_token`: `str`, A bot token, as obtained from botfather, for the bot that will be sending messages in gif workshop groups. If not provided, the user account will be used.
- `public_bot_token`: `str`, A bot token, as obtained from botfather, for the bot that will handle public queries, such as tagging and sourcing and searching, for subscribers to channels to use.
- `channels`: `list[Channel]`, A list of channel configurations, further detailed below
- `workshop_groups`: `list[Workshop]`, A list of workshop configurations, further detailed below
- `api_keys`: `dict`, A dictionary of API keys to various services, as detailed below

### Channel configuration
 TODO
 
### Workshop configuration
 TODO
 
### API key configuration
 TODO