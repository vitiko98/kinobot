#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from discord import Embed
from dotenv import load_dotenv


def _create_dirs(dir_tuple):
    for to_create in dir_tuple:
        if os.path.isdir(to_create):
            continue

        os.makedirs(to_create, exist_ok=True)
        print(f"Directory created: {to_create}")


TEST = os.environ.get("KINOBOT_TEST", "").lower().strip() == "true"

_image_extensions_registry = {"png", "jpg"}

IMAGE_EXTENSION = os.environ.get("KINOBOT_IMAGE_EXTENSION", "jpg")
if IMAGE_EXTENSION not in _image_extensions_registry:
    raise ValueError(f"Invalid image extension: {IMAGE_EXTENSION}")


APP_DIR = os.environ["KINOBOT_APP_DIR"]

load_dotenv(os.path.join(APP_DIR, "envs"))

CACHE_DIR = os.path.join(APP_DIR, "cache")
DATA_DIR = APP_DIR
LOGS_DIR = os.path.join(APP_DIR, "logs")


_create_dirs((CACHE_DIR, DATA_DIR, LOGS_DIR))


FACEBOOK_TOKEN = os.environ["FACEBOOK_TOKEN"]
FACEBOOK_TOKEN_MAIN = os.environ["FACEBOOK_TOKEN_MAIN"]
FACEBOOK_TOKEN_PT = os.environ["FACEBOOK_TOKEN_PT"]
FACEBOOK_TOKEN_ES = os.environ["FACEBOOK_TOKEN_ES"]

FACEBOOK_URL = os.environ["FACEBOOK_URL"]
FACEBOOK_URL_MAIN = os.environ["FACEBOOK_URL_MAIN"]
FACEBOOK_URL_PT = os.environ["FACEBOOK_URL_PT"]
FACEBOOK_URL_ES = os.environ["FACEBOOK_URL_ES"]

FACEBOOK_INSIGHTS_TOKEN = os.environ["FACEBOOK_INSIGHTS_TOKEN"]

RECENTLY_ADDED_HOOK = os.environ["RECENTLY_ADDED_HOOK"]

SUBS_DIR = os.environ["SUBS_DIR"]
FONTS_DIR = os.environ["FONTS_DIR"]

TMDB_KEY = os.environ["TMDB_KEY"]
FANART_KEY = os.environ["FANART"]

RADARR_TOKEN = os.environ["RADARR_TOKEN"]
SONARR_TOKEN = os.environ["SONARR_TOKEN"]
RADARR_URL = os.environ["RADARR_URL"]
SONARR_URL = os.environ["SONARR_URL"]
SONARR_ROOT_DIR = os.environ["SONARR_ROOT_DIR"]
RADARR_ROOT_DIR = os.environ["RADARR_ROOT_DIR"]
MOVIES_DIR = os.environ["MOVIES_DIR"]
TV_SHOWS_DIR = os.environ["TV_SHOWS_DIR"]

LAST_FM_KEY = os.environ["LAST_FM"]

DISCORD_TEST_WEBHOOK = os.environ["DISCORD_TEST_WEBHOOK"]
DISCORD_MISC_WEBHOOK = os.environ["DISCORD_TEST_WEBHOOK"]
DISCORD_ANNOUNCER_WEBHOOK = os.environ["DISCORD_ANNOUNCER_WEBHOOK"]
DISCORD_ADDITION_WEBHOOK = os.environ["DISCORD_ADDITION_WEBHOOK"]
DISCORD_TRACEBACK_WEBHOOK = os.environ["DISCORD_TRACEBACK_WEBHOOK"]
DISCORD_ADMIN_WEBHOOK = os.environ["DISCORD_ADMIN_WEBHOOK"]

DISCORD_ADMIN_TOKEN = os.environ["DISCORD_ADMIN_TOKEN"]
DISCORD_PUBLIC_TOKEN = os.environ["DISCORD_PUBLIC_TOKEN"]
DISCORD_PUBLIC_TOKEN_TEST = os.environ["DISCORD_PUBLIC_TOKEN_TEST"]
DISCORD_PUBLIC_FOREIGN_TOKEN = os.environ["DISCORD_PUBLIC_FOREIGN_TOKEN"]

KINOBOT_ID = os.environ["KINOBOT_ID"]


PATREON_ACCESS_TOKEN = os.environ["PATREON_ACCESS_TOKEN"]


YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]

KINOBASE = os.environ["KINOBASE"]

TWITTER = "https://twitter.com/kinobot2001"
PATREON = "https://patreon.com/kinobot"
WEBSITE = "https://kino.caretas.club"
GITHUB_REPO = "https://github.com/vitiko98/kinobot"
DISCORD_INVITE = "https://discord.gg/ZUfxf22Wqn"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/original"
TMDB_BASE = "https://www.themoviedb.org/movie"
FANART_BASE = "http://webservice.fanart.tv/v3"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3/videos"
PATREON_API_BASE = "https://www.patreon.com/api/oauth2/v2"
MET_MUSEUM_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
MET_MUSEUM_WEBSITE = "https://www.metmuseum.org/art/collection"
DISCORD_BOT_INVITE = "https://discord.com/api/oauth2/authorize?client_id=849454773047656459&permissions=2148006976&scope=bot"
PATREON_CAMPAIGN_ID = "6141662"
DISCORD_PERMISSIONS_INTEGER = "2148006976"
VERIFIER_ROLE_ID = "806562776847220798"


STORIES_DIR = os.environ["STORIES_DIR"]

STARS_DIR = os.path.join(STORIES_DIR, "stars")

FRAMES_DIR = os.path.join(DATA_DIR, "frames")
CACHED_FRAMES_DIR = os.path.join(CACHE_DIR, "frames")

LOGOS_DIR = os.path.join(DATA_DIR, "logos")

STORY_FONT = os.path.join(FONTS_DIR, "GothamMedium_1.ttf")
STARS_PATH = os.path.join(STORIES_DIR, "stars")

BACKDROPS_DIR = os.path.join(DATA_DIR, "backdrops")

BUGS_DIR = os.path.join(LOGS_DIR, "bugs")

DIRS = (FRAMES_DIR, CACHED_FRAMES_DIR, BACKDROPS_DIR, LOGOS_DIR, BUGS_DIR)

_create_dirs(DIRS)


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

LANGUAGE_SUFFIXES = {
    "en": "en",
    "es": "es-MX",
    "pt": "pt-BR",
}

PATREON_TIER_IDS = {"6672690": "auteur", "6672568": "director"}

FB_INFO = (
    f"💗 Support Kinobot: {PATREON}\n🎬 Explore the collection (~1000 movies): {WEBSITE}"
)

_PERMISSIONS = (
    "You reached your free daily limit (7 requests)! Please support the bot becoming a "
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
    value="6$/mo - Same as director, but with more love and access to future features",
    inline=True,
)
PERMISSIONS_EMBED.add_field(
    name='"I\'m already subscribed!"',
    value="If you already paid and this keeps showing, don't forget to link your Discord"
    " account to your Patreon account.",
    inline=False,
)
PERMISSIONS_EMBED.set_footer(
    text="Note: Subscriptions can take up to 10 minuted to get activated."
)
PERMISSIONS_EMBED.add_field(
    name="Links",
    value=f"[Kinobot's Patreon]({PATREON}). "
    f"If you still have problems, ask for support: [Official Discord server]({DISCORD_INVITE})",
    inline=False,
)

API_HELP_EMBED = Embed(title="Human readable documentation links")
API_HELP_EMBED.add_field(
    name="Documentation main page",
    value=f"[Link]({WEBSITE}/docs)",
    inline=False,
)
API_HELP_EMBED.add_field(
    name="Bracket flags (e.g. [quote --plus 700])",
    value=f"[Link]({WEBSITE}/docs/brackets.html)",
    inline=False,
)
API_HELP_EMBED.add_field(
    name="Full request flags (e.g. !req Movie [quote] --font helvetica)",
    value=f"[Link]({WEBSITE}/docs/postprocessing.html)",
    inline=False,
)

# Just for fun
WEBHOOK_PROFILES = (
    {
        "username": "Ye",
        "avatar_url": "https://i.ytimg.com/vi/fEHcsNmu6Yc/hqdefault.jpg",
    },
    {
        "username": "Among Us",
        "avatar_url": "https://pioneeroptimist.com/wp-content/uploads/2021/03/among-us-6008615_1920-838x900.png",
    },
    {
        "username": "Future",
        "avatar_url": "https://lastfm.freetls.fastly.net/i/u/300x300/443f94378a1e4642c62c2b039df1ecad.png",
    },
    {
        "username": "Young Thug",
        "avatar_url": "https://lastfm.freetls.fastly.net/i/u/300x300/0bddfa49e1d95f620267fac8f4663a60.png",
    },
    {"username": "Tyler", "avatar_url": "https://i.imgur.com/b9c8AXm.png"},
    {
        "username": "Xi Jinping",
        "avatar_url": "https://asiasociety.org/sites/default/files/styles/1200w/public/1/150827_xi_0.jpg",
    },
    {
        "username": "Lenin",
        "avatar_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/17/Vladimir_Lenin.jpg/1200px-Vladimir_Lenin.jpg",
    },
)

print(f"Test mode: {TEST}; Image extension: {IMAGE_EXTENSION}")
