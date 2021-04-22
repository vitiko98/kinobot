#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import glob
import json
import logging
import logging.handlers as handlers
import os
import re
import subprocess
import urllib
from typing import Optional, Tuple

import requests
import unidecode
from PIL import Image
from pymediainfo import MediaInfo

from .cache import region
from .exceptions import EpisodeNotFound

_EXTENSIONS = ("*.mkv", "*.mp4", "*.avi", "*.m4v")

_IS_EPISODE = re.compile(r"s[0-9][0-9]e[0-9][0-9]")

_EPISODE_RE = re.compile(r"(?:s|season)(\d{1,2})(?:e|x|episode|\n)(\d{1,2})")

_LOG_FMT = "%(asctime)s - %(module)s.%(levelname)s: %(message)s"

_NON_ALPHA = re.compile(r"([^\s\w]|_|/)+")
_SPACES = re.compile(r"\s+")

_ARGS_RE = re.compile(r"(--?[\w-]+)(.*?)(?= -|$)")

logger = logging.getLogger(__name__)


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
    matches = _ARGS_RE.findall(content)
    result = {}
    for match in matches:

        if match[0] not in args:
            continue

        content = content.replace(match[0], "")

        match_ = match[0].lstrip("-").replace("-", "_")

        if not match[1]:
            result[match_] = True
        else:
            content = content.replace(match[1], "")
            try:
                value = float(match[1].strip())
            except ValueError:
                value = match[1].strip()

            result[match_] = value

    logger.debug("Final content: %s", content)

    return content, result


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
        logger.info("ffprobe failed. Using mediainfo")
        media_info = MediaInfo.parse(path, output="JSON")
        if isinstance(media_info, str):
            display_aspect_ratio = float(
                json.loads(media_info)["media"]["track"][1]["DisplayAspectRatio"]
            )
        else:
            raise TypeError(type(media_info)) from error

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
    result = subprocess.run(command, stdout=subprocess.PIPE, timeout=60)
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
    " Download an image url and convert it to a PIL.Image object. "
    response = requests.get(url, stream=True, timeout=5)
    response.raise_for_status()
    response.raw.decode_content = True
    return Image.open(response.raw)


def download_image(url: str, path: str) -> str:
    urllib.request.urlretrieve(url, path)  # type: ignore
    return path


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
        return tuple([rgb_to_hex(color) for color in colors])
    except Exception as error:
        logger.error(error, exc_info=True)
        return "#000000", "#FFFFFF"


def rgb_to_hex(colortuple: tuple) -> str:
    return "#" + "".join(f"{i:02X}" for i in colortuple)


def gen_list_of_files(path: str):
    """
    Scan recursively for video files.

    :param path: path
    """
    for ext in _EXTENSIONS:
        for file_ in glob.glob(os.path.join(path, "**", ext), recursive=True):
            yield file_


def is_episode(title: str) -> bool:
    """
    >>> title = "the wire s01E01"
    >>> is_episode(title)
    >>> True
    """
    return _IS_EPISODE.search(title.lower()) is not None


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


def init_log(level: str = "INFO", path: Optional[str] = None, when: str = "midnight"):
    """
    :param level: log level name
    :param path: optional rotable path to append logs
    :param when: when param for TimedRotatingFileHandler
    """
    logger = logging.getLogger()
    level = logging.getLevelName(level)
    logger.setLevel(level)

    formatter = logging.Formatter(fmt=_LOG_FMT, datefmt="%H:%M:%S")

    if path is not None:
        rotable = handlers.TimedRotatingFileHandler(path, when=when)
        rotable.setFormatter(formatter)
        logger.addHandler(rotable)

    printable = logging.StreamHandler()

    printable.setFormatter(formatter)

    logger.addHandler(printable)
