# /scripts/envs.sh.sample
import os
import sys


try:
    FACEBOOK = os.environ["FACEBOOK"]
    FILM_COLLECTION = os.environ["FILM_COLLECTION"]
    FRAMES_DIR = os.environ["FRAMES_DIR"]
    NSFW_MODEL = os.environ["NSFW_MODEL"]
    MAGICK_SCRIPT = os.environ["MAGICK_SCRIPT"]
    FONTS = os.environ["FONTS"]
    TMDB = os.environ["TMDB"]
    RANDOMORG = os.environ["RANDOMORG"]
    RADARR = os.environ["RADARR"]
    RADARR_URL = os.environ["RADARR_URL"]
    REQUESTS_JSON = os.environ["REQUESTS_JSON"]
    OFFENSIVE_JSON = os.environ["OFFENSIVE_JSON"]
    KINOBASE = os.environ["KINOBASE"]
    REQUESTS_DB = os.environ["REQUESTS_DB"]
    DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
    DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
    KINOLOG = os.environ["KINOLOG"]
    KINOLOG_COMMENTS = os.environ["KINOLOG_COMMENTS"]
except KeyError as error:
    sys.exit(f"Environment variable not set: {error}")
