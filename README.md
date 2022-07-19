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
- `caption`: `str` (optiona), If provided, used as a jinja2 template string, which is passed a dictionary of tag names to lists of tag values, to format a caption for the destination.

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
- `text`: `str` (optional, default is empty). The string to use as a caption for the tweet. These are provided as jinja template strings, with `tags` variable provided as a dictionary of tag names to lists of tag values. e.g. A "text" value of "Source: {{ tags['source'] | first }}" will result in a caption "Source: https://..." for your given source URL.
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
- `default_destination`: (`str|int`) (optional), If set, is the telegram handle for the default channel videos sent from this workshop will go to.ß

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
As a general rule, commands should be posted as a reply to the video they are referring to, and will then reply to the command with their results.

### Channel forward tag helper
Just sets the source tag for any videos forwarded from a public channel.

### Chart helper
Takes commands of the form: `chart {destination} {tag_name}` where `{destination}` is the handle of a telegram channel the bot is managing, and `{tag_name}` is the name of a tag field. It will then generate a pie chart of from the frequency distribution of all the values of that tag in that channel.

### Chunk split helper
Cuts a video into regularly sized chunks with commands of the form `chunk {duration}`. The duration can either be given as a number (iterpreted as a number of seconds), or an iso8601 duration.

### Delete helper
Takes commands of the form: `delete family` or `delete branch`, as a reply to another message. This helper checks that the user has telegram permissions to delete things in this chat.  
If `delete branch` is specified, it will delete the message the comamnd is replying to, as well as any messages which are replies to that, or replies to that, all the way down. This includes the command message.  
If `delete family` is specified, it will delete the message the command is replying to, any messages those messages are replying to, all the way up, and anything replying to any of those messages, all the way down. This includes the command message.

### Download helper
Scans messages for links, and will attempt to download them using the [Youtube Downloader](https://github.com/yt-dlp/yt-dlp) tool. Skips certain links that specialised handlers can handle, such as imgur, fa, and msg handlers. If the link is to a playlist, it will only download the first video of the list.

### Duplicate helper
Attempts to check videos for whether duplicates have been seen elsewhere in the system, whether in channels or workshops. When a new video is posted, it will automatically be split into frames (at 5 fps), and those images will be hashed with dHash from the [python imagehash library](https://github.com/JohannesBuchner/imagehash). If there are any matches, a notice will be posted as a reply to the video.  
You can also reply to a video with `check` and it will check that video and post a reply with the results.

### FA Helper
A specific handler for downloading and processing gif files from the furaffinity website.

### FFProbe helper
When a command is sent as a reply to a video, this helper uses ffprobe to get information about the video.  
- `ffprobe` or `stats` will return the full ffprobe information dump for the video.
- `duration` will return the video duration, in seconds.
- `resolution` or `size` will return the video resolution in pixels.

### Find helper
This hander will attempt to find a video in a playlist, which matches the video which the user is replying to.
Use `find {playlist link}` and it will search the playlist for a matching video, and respond with the video and link.

### Imgur gallery helper
A specific handler for downloading entire imgur galleries and posts. All gifs and videos in an image gallery will be turned into videos and posted as a reply to the message with the gallery link.

### Menu helper
Has no specific commands, but handles all menus in the application. (Such as those generated by send helper, scene split helper, schedule helper, tag helper, etc.) Some menus can also be replied to, such as tagging menus, and this helper will handle those messages.

### Merge helper
Merges or joins videos together. If videos are not the same resolution, videos will be scaled and black bars will be padded to make all videos the same resolution as the first video in the sequence. This helper takes 3 different commands
- `merge {link...}` Can be sent as a reply to a video, or with a list of video message links, and will combine those videos into one video, with the reply message or the first link in the list being first, and the other links in the list in order.
- `append {link...}` Sent as a reply to a video with a list of video message links, and will combine those linked videos onto the end of the reply target video.
- `prepend {link...}` Sent as a reply to a video with a list of video message links, and will combine those linked videos onto the start of the reply target video.

### MSG helper
A specific handler for downloading and processing gif and webm submissions on the e621 website.

### Reverse helper
Takes commands of the form: `reverse`, and will reverse the video the command is replying to.

### Scene split helper
Takes commands of the form: `split scenes {threshold}` where `{threshold}` is an optional argument, defaulting to 30.  
Uses the [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) library to detect the scenes in a video, and then splits the video up into those scenes. It will give a menu prompt saying how many scenes the video will be split into before it actually splits the video and posts the scenes.  
Use a higher threshold to make it split into fewer scenes, and a lower threshold to make it split into more scenes.

### Schedule helper
Handles channel queue scheduling, and automatic posting. Will ensure every non-empty queue with a scheule will have a menu asking whether to post a specified video into the channel at a specified time.
If a queue becomes empty, a message will be posted that the queue is empty.  
Also takes commands of the form `schedule`, as a reply to a video in a queue, to schedule that video as the next one to send to the channel.

### Send helper
Takes commands of the form `send` to present a menu to the user asking which channel to send the specified video to. Will only suggest channels that the user has telegram permissions to post in.
If there are any configured tags for the channel, it will prompt the user to set those tags.
If there is a queue configured for the channel, it will ask the user whether to send straight to the channel, or whether to send to the queue.

### Stabilise helper
Takes commands of the form `stabilise`, (`stabilize`, `stab`, `unshake`, `deshake` all also accepted) and will attempt to stabilise the video using [ffmpeg's "deshake" video filter](https://ffmpeg.org/ffmpeg-filters.html#deshake)

### Subscription helper
Manages subscriptions. There are various types of subscriptions for different sites. All subscriptions are checked once an hour, and results, or errors, are posted to the chat they were created in. Takes commands of the form:
- `sub list`: Lists subscriptions active in the current chat
- `sub {link}`: Creates a subscription to the specified link. Subscription handlers will attempt to determine which handler can handle the link
- `sub remove {link}`: Removes the subscription to the specified link.
The available types of subscription are listed below

#### Imgur subscription
Subscription to a given imgur tag or search, such as https://imgur.com/t/deer

#### Instagram subscription
Subscription to a given instagram account. This subscription type is only available if `instagram.bibliogram_url` is specified in the API keys configuration.

#### Reddit subscription
Subscription to a given subreddit. This subscription type is only available if reddit API keys have been added to configuration.

#### RSS subscription
Subscription to an RSS feed. Entries on the feed will attempt to download using youtube DL

#### Telegram subscription
Subscriptions to a telegram caht or channel. Can be a public channel, or any chat that the user who is running gif pipeline is in. The chat will be checked every hour, and any videos, gifs, or links to videos/gifs will be posted to the subscription target.

#### Twitter subscription
Subscription to a twitter feed. Uses nitter rss feeds, and hence `twitter.nitter_url` must be configured in the API key configuration for this subscription type to be enabled. Feed links can be suffixed with `/media` to only check tweets with media, or `/with_replies` to check tweets which are posted as replies.

#### Unitialised subscription
This subscription exists for startup purposes. As youtube-dl support can change with time, any subscriptions which do not seem to be able to be handled when gif pipeline starts up, will be loaded as unitialised subscriptions, and will post an error every hour until they are removed, or they can find a subscription type that supports them.

#### Youtube DL subscription
This subscription type uses youtube-dl to download the feed link as a playlist, and checks that playlist for new items, posting any new items in the subscription target chat.

### Tag helper
Handles tagging of videos. All tags are handled as a set of values for a given tag name. Takes replies to videos with commands of the form:
- `tags`: Posts all the tags and tag values for the video
- `tag {tag_name}`: Posts all the values the video has for a specific tag name
- `tag remove {tag_name}`: Removes all values for a specific tag name
- `tag {tag_name} {tag_value}`: Adds a tag value to the video for the specified tag name
- `tag remove {tag_name} {tag_value}`: Removes the given value from the video for the specified tag name

### Telegram gif helper
Converts a video into a telegram "gif", which means removing the audio track and ensuring it's an .mp4 under 8MB and under 1280px wide/tall. It also defaults to ensuring video is 30fps, as 60fps video plays slow on older phones.
Additional arguments can be provided, for example:
- `720x720` would ensure the video is no more than `720` pixels wide and `720` pixels tall. These numbers are used as a bounding box, and aspect ratio is preserved. This defaults to `1280x1280`
- bitrate can be specified with an argument ending with `bps` or `b/s`. This bitrate will be the target for the video. `mbps` and `kbps` can also be specified. This will default to the highest it can be for the video to fit in 8MB
- framerate can be specified with an argument ending with `fps`. This defaults to 30fps

### Update yt dl helper
Takes an argument of the form `update youtube downloader` (and synonyms for yt-dl) and will download a new version of yt-dlp directly [from the github](https://github.com/yt-dlp/yt-dlp) and install it for future downloads and subscriptions.

### Video crop helper
Crops a video. All measurements are given in percentages. Arguments are given as keyword value pairs, for example, `crop left 30 top 20`. Available keywords are:
- `left` or `l`. Crops a specified percentage of the total width of the video from the left side of the video
- `right` or `r`. Crops a specified percentage of the total width of the video from the right side of the video
- `top` or `t`. Crops a specified percentage of the height of the video from the top side of the video
- `bottom` or `b`. Crops a specified percentage of the height of the video from the bottom of the video
- `width` or `w`. Crops the width of a video down to the specified percentage of the current width. Cannot be specified with `left` or `right`
- `height` or `h`. Crops the height of a video down to the specified percentage of the current height. Cannot be specified with `top` or `bottom`

### Video cut helper
Cuts the length of a video. Takes a command of the form `cut {start} {end}` where start and end are timestamps in seconds. User can also use the strings "start" to specify the start of the video, and "end" to specify the end. For example, `cut start 5` to get the first 5 seconds of the video, or `cut 15 end` to get the video from 15 seconds in, to the end.  
Commands can also be given as `cut out {start} {end}` which will then cut the video from the start to the specified start timestamp, and join that to the video from the specified end timestamp to the end. Effectively cutting the specified time range out of the video.

### Video helper
Takes the same arguments as the telegram gif helper, but does not remove the audio track. Takes commands of the form `video`

### Video rotate helper
Rotates or flips video. Takes commands of the form `rotate {direction}` or `flip {axis}`.
Available rotation directions are: `clockwise`, `anticlockwise`, and `180`. There are aliases such as `right` and `left`.
Available flip axes are: `horizontal` and `vertical`

### Zip helper
If a zip file is sent to a workshop, this helper will check the zip file for any video or .gif files, and turn them into videos and post them. This can be useful for importing .gif files into telegram without the telegram client mangling them into a small resolution version.

## Public helpers
There are also public helpers, which are helpers that channel subscribers can use with the public bot instance, to request information on gifs from the channels.

### Public tag helper
If a message is forwarded from one of the channels monitored by gif pipeline, this helper will tell you the tags for that video.