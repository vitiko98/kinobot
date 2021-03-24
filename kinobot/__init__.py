import os
import sys

from appdirs import user_cache_dir, user_log_dir, user_data_dir
from dotenv import find_dotenv, load_dotenv

# Reference: /scripts/envs.sh.template

# The .env file is optional. Environment variables can be sourced from
# the bash script shown above.
dot_env = find_dotenv()
if dot_env:
    load_dotenv(dot_env)

APP_NAME = "kinobot"

KINOLOG_PATH = user_log_dir(APP_NAME)
CACHE_DIR = user_cache_dir(APP_NAME)
DATA_DIR = user_data_dir(APP_NAME)

FRAMES_DIR = os.path.join(CACHE_DIR, "frames")
CACHED_FRAMES = os.path.join(CACHE_DIR, "cached_frames")

[
    os.makedirs(user_dir, exist_ok=True)
    for user_dir in (FRAMES_DIR, CACHED_FRAMES, KINOLOG_PATH, DATA_DIR)
]

KINOLOG = os.path.join(KINOLOG_PATH, "kinobot.log")
KINOLOG_COMMENTS = os.path.join(KINOLOG_PATH, "comments.log")

try:
    FACEBOOK = os.environ["FACEBOOK"]
    FACEBOOK_TV = os.environ["FACEBOOK_TV"]
    FACEBOOK_MUSIC = os.environ["FACEBOOK_MUSIC"]
    FILM_COLLECTION = os.environ["FILM_COLLECTION"]
    EPISODE_COLLECTION = os.environ["EPISODE_COLLECTION"]
    DATABASES_DIR = os.environ["DATABASES_DIR"]
    NSFW_MODEL = os.environ["NSFW_MODEL"]
    KINOSTORIES = os.environ["KINOSTORIES"]
    FONTS = os.environ["FONTS"]
    TMDB = os.environ["TMDB"]
    RANDOMORG = os.environ["RANDOMORG"]
    FANART = os.environ["FANART"]
    RADARR = os.environ["RADARR"]
    SONARR = os.environ["SONARR"]
    RADARR_URL = os.environ["RADARR_URL"]
    SONARR_URL = os.environ["SONARR_URL"]
    REQUESTS_JSON = os.environ["REQUESTS_JSON"]
    OFFENSIVE_JSON = os.environ["OFFENSIVE_JSON"]
    LAST_FM = os.environ["LAST_FM"]
    DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
    DISCORD_WEBHOOK_TEST = os.environ["DISCORD_WEBHOOK_TEST"]
    DISCORD_TRACEBACK = os.environ["DISCORD_TRACEBACK"]
    DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
    KINOBOT_ID = os.environ["KINOBOT_ID"]
    KINOSONGS = os.environ["KINOSONGS"]
    TWITTER_KEY = os.environ["TWITTER_KEY"]
    TWITTER_SECRET = os.environ["TWITTER_SECRET"]
    TWITTER_ACCESS_TOKEN = os.environ["TWITTER_ACCESS_TOKEN"]
    TWITTER_ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]
except KeyError as error:
    sys.exit(f"Environment variable not set: {error}")

MUSIC_DB = os.path.join(DATABASES_DIR, "kinomusic.db")
KINOBASE = os.path.join(DATABASES_DIR, "kinobase.db")
REQUESTS_DB = os.path.join(DATABASES_DIR, "requests.db")
DISCORD_DB = os.path.join(DATABASES_DIR, "discord.db")
TWITTER_DB = os.path.join(DATABASES_DIR, "twitter.db")
WEB_FRAMES = os.path.join(DATA_DIR, "web_frames")
