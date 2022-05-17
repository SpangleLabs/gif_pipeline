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
- `pipeline_bot_token`: `str` (optional), A bot token, as obtained from botfather, for the bot that will be sending messages in gif workshop groups. If not provided, the user account will be used.
- `public_bot_token`: `str` (optional), A bot token, as obtained from botfather, for the bot that will handle public queries, such as tagging and sourcing and searching, for subscribers to channels to use.
- `channels`: `list[Channel]`, A list of channel configurations, further detailed below
- `workshop_groups`: `list[Workshop]`, A list of workshop configurations, further detailed below
- `api_keys`: `dict`, A dictionary of API keys to various services, as detailed below

### Channel configuration
Each channel is a dictionary in the base `channels` list. They have these keys:
- `handle`: `str|int`, the telegram handle of the channel. A string if public channel, or the channel ID integer if it's a private channel. Does not need any "-100" prefix.
- `_note`: `str` (optional), Not parsed, but can be used to clarify the purpose of channels, especially useful for private ones.
- `queue`: `Queue` (optional), queue configuration, see below for details. If provided the channel will use a group chat as a queue, to buffer a set of gifs before sending them.
- `read_only`: `boolean` (optional, default: False). If set to true, the channel will be considered read only. It will be indexed for duplicate detection, but will not be given as a destination for sending
- `send_folder`: `str` (optional), If provided, this channel will be in the folder with the given name when user requests to send a video (and has permission to access this channel). Folders can be nested by using a slash (`/`). For example, providing `animals/mammals` will mean that this channel will appear in the "mammals" folder inside the "animals" folder, along with any other channels configured with the same `send_folder`.
- `note_time`: `boolean` (optional, default: False). If provided, and true, the send confirmation menu will note to the user when the last message was sent to the destination channel.
- `tags`: `Tags` (optional). If provided, this will provide configuration for suggested tags for videos sent to the given channel, see below for details.
- `twitter`: `Twitter` (optional). If provided, videos sent to this channel will also be sent to twitter. See below for details

#### Queue configuration
Configuration for a channel queue. Must be a group chat, rather than another channel.
- `handle`: `str|int`. The telegram handle of the queue. A string if public (which would be odd), or the chat ID if private. Should be a positive integer, not prefixed by 100
- `duplicate_detection`: `boolean` (optional, default: True). Whether to enable duplicate detection in this queue, checking whether videos here have been seen before, or whether videos elsewhere are here.
- `schedule`: `Schedule` (optional), if provided, gif pipeline will automatically post from the queue to the channel according to the schedule. It will prompt which video will be sent next, and when, and give you the option to enable automatically posting it at the specified time. 

##### Schedule configuration
Provided to a queue, this will cause it to prompt to automatically post from the queue to the channel according to this schedule.
- `min_time`: `str`, an [iso8601 duration](https://en.wikipedia.org/wiki/ISO_8601#Durations) string, the minimum time between automatically prompted posts in the channel.
- `max_time`: `str` (optional), an iso8601 duration string which, if provided, will serve as the maximum time between posts in the channel, and the automatic prompt will pick a random time between the minimum time and maximum time.
- `order`: `str` (optional, default: "random"). Can be one of: `random`, `oldest_first`, `newest_first`, and will decide whether the automatic posting helper will suggest posting the oldest video in the queue first, the newest video, or will select a video at random.

#### Tags configuration
The tag configuration is the suggested tags for videos being posted to a given channel. The keys of the dictionary should be the names of the tags, and then the values should be a dictionary with the following keys, or an empty dictionary to default to defaults:
- `type` (str, default: "normal"), Can be one of: `normal`, `single`, `text`, or `gnostic`.
  - `type=normal`: A list of all the tag values which have been seen before will be presented to the user, who can then select whichever are appropriate, which will be stored for the video.
  - `type=single`: A list of all the tag values which have been seen before will be presented to the user, who can then select **one of** the listed tags which will be stored for the video.
  - `type=text`: The user will be prompted to enter a custom text value for the tag
  - `type=gnostic`: A list of all the tag values which have been seen before will be presented to the user, who can then select which tags apply, and which do not. On saving, the list of which apply and the list of which are not selected, will both be saved, which means future tag values can be added, and will not automatically not-apply to previous videos.
By default, a `source` tag will be added to videos by download helpers, which will contain the link the video was originally downloaded from.

#### Twitter configuration
If this is provided, videos sent to this channel will also be posted to twitter.
To use this functionality, you must also provide "consumer_key" and "consumer_secret" in the API keys configuration section for twitter.
- `account`: `TwitterAccount`. The account tokens for the twitter account to post this video.
- `text`: `str` (optional, default is empty). The string to use as a caption for the tweet. These are provided as f-string format strings, with `tags` variable provided as a dictionary of tag names to values concatenated with commas. e.g. A "text" value of "Source: {tags[source]}" will result in a caption "Source: https://..." for your given source URL.
- `reply`: `dict` (optional). If this is provided, it is another twitter configuration object, with information for automatically posting another tweet as a reply to the original one. The reply will not have a video, so the `text` field is no longer optional. The `reply` field is available, and optional, in case you want to make a longer chain of tweets. The `account` field is also available, and is optional, so that the reply can be posted from a separate twitter account. If the `account` field is not provided, the reply will be posted by the same account as the tweet it is replying to.

##### TwitterAccount configuration
A dictionary containing the account access token and access secret for the given twitter account. These are generated via oauth, and can be generated by running the `get_twitter_tokens.py` script in the `scripts` directory.
- `access_token`: `str` The access token for the account posting videos on twitter
- `access_secret`: `str` The access token secret for the account posting videos on twitter

### Workshop configuration
Workshops are group chats where a user can interact with the gif pipeline to edit and process videos and links. Permissions are handled on the telegram side, meaning anyone in one of these groups can use the functionality of the bot to download videos or edit them. (When sending to channels however, the users' permissions are checked for each available channel)
- `handle`: (`str|int`) The telegram handle for the workshop group. Should be the public username (if it's a public groupchat) or an integer chat ID, which should be positive and without "100" prefix.
- `_note`: `str` (optional), Not parsed, but can be used to clarify the purpose of workshops, especially useful for private groupchats, with otherwise only have a numeric ID in the config file.
- `duplicate_detection`: (`boolean`) Whether to enable duplicate detection notifications (and video hashing) for the workshop
 
### API key configuration
This section stores various API keys or other details for third party services. Generally used by helpers. Most helpers should check for the presence of the API keys they require before attempting to support those services.
- `imgur`: API key details for Imgur, an image hosting service
  - `imgur.client_id`: (`str`) Client ID for the imgur API. You can register that at [Imgur's API site](https://api.imgur.com/oauth2/addclient). The client secret is only needed for posting to imgur, and hence not needed by gif pipeline.
- `reddit`: API access details for reddit, a social media site. Details are generally obtained at [reddit's API preferences page](https://www.reddit.com/prefs/apps)
  - `reddit.client_id`: (`str`) This is the client_id for the reddit API
  - `reddit.client_secret`: (`str`) This is the client_secret for the reddit API
  - `reddit.owner_username`: (`str`) This is your reddit username, which is provided in the user agent of requests to reddit's API
- `twitter`: Details for twitter subscriptions, as well as for posting to twitter accounts
  - `twitter.nitter_url`: (`str`) This is used by the twitter subscription type. It should be the URL of a nitter instance with RSS enabled.
  - `twitter.consumer_key`: (`str`) Used by twitter posting, consumer_key as required by `scripts/get_twitter_token.py`. Generated on the [twitter developer portal site](https://developer.twitter.com/en/docs/apps/overview). [This guide](https://medium.com/geekculture/how-to-create-multiple-bots-with-a-single-twitter-developer-account-529eaba6a576) can also be helpful.
  - `twitter.consumer_secret`: (`str`) Used by twitter posting, consumer_secret as required by `scripts/get_twitter_token.py` in the same was as the consumer_key above.
- `instagram`
  - `instagram.bibliogram_url`: (`str`) This us used by the instagram subscription type. It should be the URL of a bibliogram instance with RSS enabled.

## Helpers
The pipeline has many "helpers", which are classes which handle different types of user requests in workshop groups. These are used to edit videos, and manage tags, and such.

TODO

## Public helpers
There are also public helpers, which are helpers that channel subscribers can use with the public bot instance, to request information on gifs from the channels.

TODO
