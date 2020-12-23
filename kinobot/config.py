# Open the /scripts/envs.sh.sample file for more info.
import os
import sys

try:
    FACEBOOK = os.environ["FACEBOOK"]
    FILM_COLLECTION = os.environ["FILM_COLLECTION"]
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
    KINOLOG = os.environ["KINOLOG"]
    KINOLOG_COMMENTS = os.environ["KINOLOG_COMMENTS"]
except KeyError as error:
    sys.exit(f"Environment variable not set ({error})")
