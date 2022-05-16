import json

import tweepy

with open("config.json", "r") as f:
    config = json.load(f)
    consumer_key = config["api_keys"]["twitter"]["consumer_key"]
    consumer_secret = config["api_keys"]["twitter"]["consumer_secret"]

auth = tweepy.OAuthHandler(
    consumer_key, consumer_secret,
    callback="oob"
)
print(auth.get_authorization_url())
verifier = input("Input PIN: ")
auth.get_access_token(verifier)
access_token = auth.access_token
access_token_secret = auth.access_token_secret
print(f"Access token: {access_token}")
print(f"Access secret: {access_token_secret}")
