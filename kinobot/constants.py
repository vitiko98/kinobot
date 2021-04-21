#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from appdirs import user_cache_dir, user_data_dir, user_log_dir
from discord import Embed
from dotenv import find_dotenv, load_dotenv

# The .env file is optional. Environment variables can be sourced from
# the bash script shown above.
dot_env = find_dotenv()
if dot_env:
    load_dotenv(dot_env)

APP_NAME = "kinobot"

CACHE_DIR = user_cache_dir(APP_NAME)
DATA_DIR = user_data_dir(APP_NAME)
LOGS_DIR = user_log_dir(APP_NAME)

FACEBOOK_TOKEN = os.environ["FACEBOOK_TOKEN"]

RECENTLY_ADDED_HOOK = os.environ["RECENTLY_ADDED_HOOK"]
DATABASES_DIR = os.environ["DATABASES_DIR"]
STORIES_DIR = os.environ["STORIES_DIR"]
SUBS_DIR = os.environ["SUBS_DIR"]
FONTS_DIR = os.environ["FONTS"]

TMDB_KEY = os.environ["TMDB_KEY"]
FANART_KEY = os.environ["FANART"]

RADARR_TOKEN = os.environ["RADARR_TOKEN"]
SONARR_TOKEN = os.environ["SONARR_TOKEN"]
RADARR_URL = os.environ["RADARR_URL"]
SONARR_URL = os.environ["SONARR_URL"]

LAST_FM_KEY = os.environ["LAST_FM"]

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
DISCORD_WEBHOOK_TEST = os.environ["DISCORD_WEBHOOK_TEST"]
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]

KINOBOT_ID = os.environ["KINOBOT_ID"]

TWITTER_KEY = os.environ["TWITTER_KEY"]
TWITTER_SECRET = os.environ["TWITTER_SECRET"]
TWITTER_ACCESS_TOKEN = os.environ["TWITTER_ACCESS_TOKEN"]
TWITTER_ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

KINOBASE = os.path.join(DATABASES_DIR, "kinobase.db")

TWITTER = "https://twitter.com/kinobot2001"
PATREON = "https://patreon.com/kinobot"
WEBSITE = "https://kino.caretas.club"
FACEBOOK_URL = "https://www.facebook.com/certifiedkino"
FACEBOOK_URL_TV = "https://www.facebook.com/kinobotv"
GITHUB_REPO = "https://github.com/vitiko98/kinobot"
DISCORD_INVITE = "https://discord.gg/ZUfxf22Wqn"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/original"
TMDB_BASE = "https://www.themoviedb.org/movie"
FANART_BASE = "http://webservice.fanart.tv/v3"
SERVER_PATH = "/var/www/static/frames"

STARS_DIR = os.path.join(STORIES_DIR, "stars")

FRAMES_DIR = os.path.join(DATA_DIR, "frames")
CACHED_FRAMES_DIR = os.path.join(CACHE_DIR, "frames")

LOGOS_DIR = os.path.join(DATA_DIR, "logos")

STORY_FONT = os.path.join(FONTS_DIR, "GothamMedium_1.ttf")
STARS_PATH = os.path.join(STORIES_DIR, "stars")

BACKDROP_DIR = os.path.join(DATA_DIR, "backdrops")

CATEGORY_IDS = {
    "peak cringe": 1,
    "certified cringe": 2,
    "borderline kino": 3,
    "high kino": 4,
    "pleb-oriented kinema": 5,
    "cringema": 6,
    "peak kino": 7,
    "certified kino": 8,
    "hi mark kinema": 9,
    "citizen kino": 10,
}

FB_INFO = (
    f"💗 Support Kinobot: {PATREON}\n🎬 Explore the collection (~1000 movies), "
    f"your won badges, and much more: {WEBSITE}\n⭐ Give me a star on Github:"
    f"{GITHUB_REPO}"
)

_PERMISSIONS = (
    "You reached your free daily limit! Please support the bot becoming a "
    f"[patron]({PATREON}) and get access to **unlimited requests**. "
    "Here's the list of available roles and perks:"
)

PERMISSIONS_EMBED = Embed(
    title="Supporters-only feature",
    url=PATREON,
    description=_PERMISSIONS,
)
PERMISSIONS_EMBED.add_field(
    name="Director",
    value="3$/mo - Unlimited classic requests, parallels, and palettes",
    inline=True,
)
PERMISSIONS_EMBED.add_field(
    name="Auteur",
    value="6$/mo - Same as director, but with access to unlimited GIF requests!",
    inline=True,
)
PERMISSIONS_EMBED.add_field(
    name='"I already paid or recently donated!"',
    value="If you already paid and this keeps showing, please ping @vitiko at #support.",
    inline=False,
)
PERMISSIONS_EMBED.add_field(
    name="Links",
    value=f"[Kinobot's Patreon]({PATREON})",
    inline=False,
)
