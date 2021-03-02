#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import logging
import subprocess
import os
import cv2
import re
import pylast

from urllib import parse
from tempfile import gettempdir

from fuzzywuzzy import fuzz

from kinobot import LAST_FM
from kinobot.exceptions import NothingFound, NotEnoughColors
from kinobot.frame import cv2_trim, cv2_to_pil, is_bw, prettify_aspect
from kinobot.palette import get_palette_legacy, get_palette

TAGS_RE = r"\((.*)| - (.*)|[\(\[].*?[\)\]]"
YOUTUBE_BASE = "https://www.youtube.com/watch?v="
TEMP_FOLDER = gettempdir()

logger = logging.getLogger(__name__)


def extract_id_from_url(video_url):
    """
    :param video_url: YouTube URL (classic or mobile)
    """
    try:
        return parse.parse_qs(parse.urlparse(video_url).query)["v"][0]
    except KeyError:
        parsed = parse.urlsplit(video_url)
        if parsed.netloc == "youtu.be" and len(parsed.path) < 15:
            return parsed.path.replace("/", "")


def fuzzy_search_track(video_list, query):
    """
    :param video_list: list of dictionaries
    :param query: query
    :raises exceptions.NothingFound
    """
    query = query.replace("MUSIC", "").lower()

    initial = 0
    final_list = []
    for f in video_list:
        title = fuzz.ratio(query, f"{f['artist']} - {f['title']}".lower())
        if title > initial:
            initial = title
            final_list.append(f)

    item = final_list[-1]
    if initial > 59:
        return item

    raise NothingFound(
        f'Video not found: "{query}". Maybe you meant "{item["artist"]}'
        f'- {item["title"]}"? '
    )


def extract_frame_from_url(video_id, timestamp):
    """
    :param video_id: video ID from YouTube
    :param timestamp: second.millisecond string
    """
    logger.info(f"Extracting {timestamp} from video id {video_id}")

    video_url = YOUTUBE_BASE + video_id

    path = os.path.join(TEMP_FOLDER, f"{video_id}.png")

    command = f"video_frame_extractor {video_url} {timestamp} {path}"

    subprocess.call(command, stdout=subprocess.PIPE, shell=True, timeout=15)

    if os.path.isfile(path):
        logger.info("Ok")
        return path

    raise NothingFound(f"Error extracting second '{timestamp}' from video.")


def get_frame(video_id, second, millisecond):
    """
    :param video_id: video ID from YouTube
    :param second
    :param millisecond
    """
    frame = extract_frame_from_url(video_id, f"{second}.{int(millisecond*0.01)}")
    image = cv2.imread(frame)

    trim = prettify_aspect(cv2_to_pil(cv2_trim(image)))

    bw_img = is_bw(trim)

    final_img = trim
    aspect_quotient = trim.size[0] / trim.size[1]

    palette = {"image": final_img, "colors": None}
    if not bw_img:
        logger.info("Colored image found")
        logger.info(f"Aspect qotient: {aspect_quotient}")

        if aspect_quotient < 1.4:
            palette = get_palette(trim, return_dict=True)
        else:
            try:
                palette = get_palette_legacy(trim, return_dict=True)
            except NotEnoughColors:
                palette = get_palette(trim, return_dict=True)

        final_img = palette["image"]

    return {
        "final_img": final_img,
        "raw_img": trim,
        "is_bw": bw_img,
        "aspect_quotient": aspect_quotient,
        "colors": palette["colors"],
    }


def clean_garbage(text):
    """
    Remove garbage from a track title (remastered tags and alike).
    """
    return re.sub(TAGS_RE, "", text)


def search_tracks(query, limit=3, remove_extra=True):
    """
    Search for tracks on last.fm.
    """
    client = pylast.LastFMNetwork(LAST_FM)

    results = client.search_for_track("", query)

    for result in results.get_next_page()[:limit]:
        artist = str(result.artist)
        title = clean_garbage(result.title) if remove_extra else result.title
        complete = f"*{artist}* - **{title}**"

        yield {"artist": artist, "title": title, "complete": complete}
