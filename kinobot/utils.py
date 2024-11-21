#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import glob
import json
import logging
import logging.handlers as handlers
import os
import random
import re
import shutil
import subprocess
import traceback
from typing import List, Optional, Tuple, Union

from discord_webhook import DiscordEmbed
from discord_webhook import DiscordWebhook
from fuzzywuzzy import fuzz
from fuzzywuzzy import process
from PIL import Image
import requests
import unidecode
import yaml

from .cache import region
from .config import config
from .constants import BUGS_DIR
from .constants import DIRS
from .constants import TEST
from .constants import WEBHOOK_PROFILES
from .exceptions import EpisodeNotFound
from .exceptions import ImageNotFound
from .exceptions import InvalidRequest

_IS_EPISODE = re.compile(r"s[0-9][0-9]e[0-9][0-9]")

_EPISODE_RE = re.compile(r"(?:s|season)(\d{1,2})(?:e|x|episode|\n)(\d{1,4})")

_LOG_FMT = "%(asctime)s - %(module)s.%(levelname)s: %(message)s"

_NON_ALPHA = re.compile(r"([^\s\w]|_|/)+")
_SPACES = re.compile(r"\s+")

_ARGS_RE = re.compile(r"(---?[\w-]+)(.*?)(?= --|$)")

_DOTS_URL_RE = re.compile(r"(?=.*[a-z])(?<=\w)\.(?=(?![\d_])\w)")

logger = logging.getLogger(__name__)


def fuzzy_many(
    query: str, items: List, item_to_str=None, in_check=None, min_fuzz=60, limit=20
):
    query = query.lower().strip()

    fuzzy_list = []
    item_to_str = item_to_str or (lambda d: str(d))
    in_check = in_check or (lambda q, i: q.lower() in item_to_str(i).lower())
    partial_matches = []
    initial = min_fuzz

    for item in items:
        if in_check(query, item):
            partial_matches.append(item)

        fuzzy = fuzz.ratio(query, item_to_str(item))

        if fuzzy > initial:
            initial = fuzzy
            fuzzy_list.append(item)

            if fuzzy > 98:  # Don't waste more time
                break

    fuzzy_list.reverse()
    final = [*fuzzy_list, *partial_matches]
    return final[:limit]


def get_yaml_config(path: str, key: Optional[str] = None) -> dict:
    "raises: TypeError, KeyError"
    with open(path, "r") as f:
        data = yaml.safe_load(f)

    if key is not None:
        return data[key]

    return data


def get_args_and_clean(content: str, args: tuple = ()) -> Tuple[str, dict]:
    """
    >>> text = "some request [xy] [yx] --flag 2 --another-flag
    >>> get_args_and_clean(text, ("--flag", "--another-flag",))
    >>> "some request [xy] [yx]", {"flag": 2, "another_flag": True}

    :param content:
    :type content: str
    :param args:
    :type args: tuple
    :rtype: Tuple[str, dict]
    """
    matches = _ARGS_RE.findall(content.strip())
    result = {}
    for match in matches:
        logger.debug("Match: %s", match)

        if match[0] not in args:
            close = process.extract(match[0], args, limit=1)[0][0]
            raise InvalidRequest(
                f"Invalid flag: `{match[0]}`. Maybe you meant `{close}`?"
            )

        match_ = match[0].lstrip("-").replace("-", "_")

        if not match[1]:
            content = content.replace(match[0], "")
            result[match_] = True
        else:
            content = content.replace(match[0] + match[1], "")
            try:
                value = float(match[1].strip())
            except ValueError:
                value = match[1].strip()

            result[match_] = value

    logger.debug("Final content: %s", content)

    return content.strip(), result


def clean_url(text) -> str:
    """
    "Some Movie!? (1999)" -> "some-movie-1999"

    :rtype: str
    """
    text = _SPACES.sub("-", _NON_ALPHA.sub("", text))
    return unidecode.unidecode(text).lower()


@region.cache_on_arguments()
def get_dar(path: str) -> float:
    """
    Get Display Aspect Ratio from file.

    :param path: path
    :raises TypeError
    """
    try:
        logger.info("Using ffprobe")
        d_width, d_height = _get_ffprobe_dar(path)
        display_aspect_ratio = float(d_width) / float(d_height)
    except Exception as error:
        raise NotImplementedError from error

    logger.info("Extracted DAR: %s", display_aspect_ratio)

    return display_aspect_ratio


def _get_ffprobe_dar(path) -> str:
    """
    Get Display Aspect Ratio from ffprobe (Faster than MediaInfo but
    not as reliable).

    :param path: video path
    :raises subprocess.TimeoutExpired
    """
    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, timeout=60, check=True)
    return json.loads(result.stdout)["streams"][0]["display_aspect_ratio"].split(":")


def get_dominant_colors(image: Image.Image) -> Tuple[tuple, tuple]:
    """
    Get a tuple of "dominant colors" from an image.

    :param image: PIL.Image object
    """
    two_colors = image.quantize(colors=2)
    palette = two_colors.getpalette()[:6]
    return tuple(palette[:3]), tuple(palette[3:])


def url_to_pil(url: str) -> Image.Image:
    "Download an image url and convert it to a PIL.Image object."
    response = requests.get(url, stream=True, timeout=5, allow_redirects=True)
    response.raise_for_status()
    response.raw.decode_content = True
    return Image.open(response.raw)


def download_image(url: str, path: str) -> str:
    try:
        response = requests.get(url, stream=True, allow_redirects=True, timeout=10)
        response.raise_for_status()
    except requests.HTTPError as error:
        raise ImageNotFound(
            f"Error downloading image: {type(error).__name__}"
        ) from None
    else:
        logger.debug("Image downloaded")
        with open(path, "wb") as f:
            shutil.copyfileobj(response.raw, f)

        logger.debug("Saved: %s", path)

    return path


_URL_RE = re.compile(r"https?://[^\s]+")


def clean_url_for_fb(text):
    return _URL_RE.sub("redacted-url", text)


def _clean_url_for_fb(text):
    return _DOTS_URL_RE.sub("(.)", text).replace("://", "(://)")


@region.cache_on_arguments()
def get_dominant_colors_url(url: str) -> Tuple[str, str]:
    """Get a tuple of two colors (hex) from an image URL. Return black and white if
    something fails.

    :param url:
    :type url: str
    :rtype Tuple[str, str]
    """
    try:
        pil = url_to_pil(url)
        colors = get_dominant_colors(pil)

        pil.close()

        logger.debug("Extracted colors: %s", colors)
        return tuple([rgb_to_hex(color) for color in colors])  # type: ignore
    except Exception as error:
        logger.error(error, exc_info=True)
        return "#000000", "#FFFFFF"


def rgb_to_hex(colortuple: tuple) -> str:
    return "#" + "".join(f"{i:02X}" for i in colortuple)


def gen_list_from_path(path: str, folders: bool = False):
    """Scan recursively for files or folders.

    :param path:
    :type path: str
    :param folders:
    :type folders: bool
    """
    wildcard = "**" if not folders else "**"
    for file_ in glob.iglob(os.path.join(path, wildcard), recursive=True):
        yield file_


def is_episode(title: str) -> bool:
    """
    >>> title = "the wire s01E01"
    >>> is_episode(title)
    >>> True
    """
    return _IS_EPISODE.search(title.lower()) is not None or "episode:" in title


def get_episode_tuple(title: str) -> Tuple[int, int]:
    matches = _EPISODE_RE.findall(title.replace(" ", "").lower())
    if matches:
        matches = matches[0]
        if len(matches) == 2:
            try:
                season, number = [int(match) for match in matches]
                return season, number
            except ValueError:
                pass

    raise EpisodeNotFound(f"Invalid season/episode query: {title}")


def send_webhook(
    url: str,
    content: Optional[Union[str, DiscordEmbed]] = None,
    images: List[str] = None,
    ignore_test=False,
):
    """Send a Discord webhook.

    :param url:
    :type url: str
    :param content:
    :type content: Optional[Union[str, DiscordEmbed]]
    :param images:
    :type images: List[str]
    """
    if TEST is True and not ignore_test:
        logger.debug("Testing mode. Not sending webhook: %s", content)
        return None

    images = images or []
    profile = random.choice(WEBHOOK_PROFILES)
    webhook = DiscordWebhook(url, **profile)

    if isinstance(content, str):
        webhook.set_content(content[:1900])
    elif isinstance(content, DiscordEmbed):
        webhook.add_embed(content)

    for image in images:
        with open(image, "rb") as f:
            webhook.add_file(file=f.read(), filename=os.path.basename(image))

    webhook.execute()

    return None


def fmt_exception(error: Exception) -> str:
    """Format an exception in order to use it on a webhook.

    :param error:
    :type error: Exception
    """
    trace = traceback.format_exception(type(error), error, error.__traceback__)
    return "".join(trace)


def handle_general_exception(error):
    if "error_logger" not in logging.root.manager.loggerDict:
        path = os.path.join(BUGS_DIR, "error.txt")
        init_rotating_log(path, "error_logger", "ERROR")

    logging.getLogger("error_logger").error(fmt_exception(error))
    msg = f"New exception added to the bug logger: `{type(error).__name__}`"
    send_webhook(config.webhooks.traceback, msg)


def namer(name):
    if ".log" in name or name.endswith(".txt"):
        return name

    return f"{name.replace('.txt', '')}.txt"


def normalize_request_str(quote: str, lowercase: bool = True) -> str:
    quote = quote.replace("\n", " ")
    quote = re.sub(" +", " ", quote).strip()
    if lowercase:
        return quote.lower()

    return quote


def create_needed_folders():
    "Create all the needed folders for Kinobot's data."
    for dir_ in DIRS:
        if os.path.isdir(dir_):
            continue

        os.makedirs(dir_, exist_ok=True)
        logger.info("Directory created: %s", dir_)


def init_log(level: str = "DEBUG"):
    """
    :param level: log level name
    """
    logging.getLogger("urllib3").setLevel(logging.INFO)
    logger = logging.getLogger()
    logger.setLevel(logging.getLevelName(level))

    formatter = logging.Formatter(fmt=_LOG_FMT, datefmt="%H:%M:%S")

    printable = logging.StreamHandler()

    printable.setFormatter(formatter)

    logger.addHandler(printable)


def init_rotating_log(
    path: str, name: Optional[str] = None, level: str = "DEBUG", when: str = "midnight"
):
    """
    :param level: log level name
    :param path: optional rotable path to append logs
    :param when: when param for TimedRotatingFileHandler
    """
    logging.getLogger("urllib3").setLevel(logging.INFO)
    logger_ = logging.getLogger(name)
    logger_.setLevel(logging.getLevelName(level))

    formatter = logging.Formatter(fmt=_LOG_FMT, datefmt="%H:%M:%S")

    rotable = handlers.TimedRotatingFileHandler(path, when=when)
    rotable.namer = namer
    rotable.setFormatter(formatter)
    logger_.addHandler(rotable)


def sync_local_subtitles(include="*.{es-MX,en,pt-BR}.srt", dry_run=False):
    for dir_ in (config.movies_dir, config.tv_shows_dir):
        local_dir = os.path.join(config.subs_dir, os.path.basename(dir_))
        logger.debug("Local dir to sync: %s", local_dir)
        command = ["rclone", "sync", dir_, local_dir, f"--include={include}", "-P"]
        if dry_run is True:
            command.extend("--dry-run")

        logger.info("Command to run: %s", " ".join(command))
        subprocess.run(command, check=True, timeout=600)
        logger.info("OK")
