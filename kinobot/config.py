# /scripts/envs.sh.sample
import os
import sys
import logging
from datetime import datetime

PUBLISH_MINUTES = "59, 00, 01, 02, 29, 30, 31, 32"

logger = logging.getLogger(__name__)


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
    sys.exit(f"Environment variable not set: {error}")


if datetime.now().strftime("%M") not in PUBLISH_MINUTES:
    KINOBASE = KINOBASE + ".save"
    REQUESTS_JSON = REQUESTS_JSON + ".save"
    REQUESTS_DB = REQUESTS_DB + ".save"
    logger.warning("Using temporal databases")
else:
    logger.warning("Using official databases")
