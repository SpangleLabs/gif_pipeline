import tweepy

consumer_key = "--"
consumer_secret = "----"

auth = tweepy.OAuthHandler(
    consumer_key, consumer_secret,
    callback="oob"
)
print(auth.get_authorization_url())
verifier = input("Input PIN: ")
auth.get_access_token(verifier)
access_token = auth.access_token
access_token_secret = auth.access_token_secret


# try:
#     redirect_url = auth.get_authorization_url()
# except tweepy.TweepyException:
#     print("Failed to get request token.")

# access_token = ""
# access_token_secret = ""

auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
auth.set_access_token(access_token, access_token_secret)

api = tweepy.API(auth)

try:
    api.verify_credentials()
    print("Application okay")
except:
    print("Error in auth")

resp = api.update_status(status="Just testing some things, sorry")
resp2 = api.update_status(status="And testing a reply", in_reply_to_status_id=resp.id, auto_populate_reply_metadata=True)

print(resp)
print(resp2)
