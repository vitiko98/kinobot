#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import glob
import distro
import json
import logging
import os
import random
import re
import subprocess

import logging.handlers as handlers
from pathlib import Path

import numpy as np
import requests
import srt
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat
from plexapi.server import PlexServer

from kinobot import (
    FONTS,
    RANDOMORG,
    NSFW_MODEL,
    KINOBASE,
    KINOSONGS,
    OFFENSIVE_JSON,
    PLEX_TOKEN,
    PLEX_URL,
    PLEX_ACCOUNT_ID,
)
from kinobot.exceptions import (
    InconsistentImageSizes,
    InconsistentSubtitleChain,
    InvalidRequest,
    DifferentSource,
    OffensiveWord,
)

# Don't import nsfw_detector and tensoflow in testing environments.
if "arch" not in distro.linux_distribution(
    full_distribution_name=False
) or KINOBASE.endswith(".save"):
    from nsfw_detector import predict


FONT = os.path.join(FONTS, "NotoSansCJK-Regular.ttc")


POSSIBLES = {
    "1": (1, 1),
    "2": (1, 2),
    "3": (1, 3),
    "4": (2, 2),
    "5": (2, 2),
    "6": (2, 3),
}

EXTENSIONS = ("*.mkv", "*.mp4", "*.avi", "*.m4v")
SD_SOURCES = ("dvd", "480", "xvid", "divx", "vhs")
POPULAR = "00 01 02 03 05 07 09 10 12 13 15 16 17 18 19 20 21 22 23 34"
INVALID_NAME_CHARS = ("[", "]", "<", ">", "?", "!", "(", ")", "|")
RANDOMORG_BASE = "https://api.random.org/json-rpc/2/invoke"
HEADER = "The Certified Kino Bot Collection"
FOOTER = "kino.caretas.club"
MINUTE_RE = re.compile(r"[^[]*\{([^]]*)\}")


logger = logging.getLogger(__name__)


def get_dominant_colors(image):
    """
    Get a tuple of "dominant colors" from an image.

    :param image: PIL.Image object
    """
    two_colors = image.quantize(colors=2)
    palette = two_colors.getpalette()[:6]
    return tuple(palette[:3]), tuple(palette[3:])


def url_to_pil(url):
    """
    Download an image url and convert it to a PIL.Image object.

    :param url: url
    """
    response = requests.get(url, stream=True, timeout=5)
    response.raw.decode_content = True
    return Image.open(response.raw)


def get_random_integer(start=0, end=1000):
    """
    Get a random integer from random.org.

    :param start: start
    :param end: end
    """
    params = {
        "jsonrpc": "2.0",
        "method": "generateIntegers",
        "params": {
            "apiKey": RANDOMORG,
            "n": 1,
            "min": start,
            "max": end,
            "replacement": True,
            "base": 10,
        },
        "id": 6206,
    }
    headers = {"content-type": "application/json; charset=utf-8"}

    logger.info(f"Getting random integer from random.org ({start}, {end})")
    response = requests.post(RANDOMORG_BASE, data=json.dumps(params), headers=headers)
    return json.loads(response.content)["result"]["random"]["data"][0]


def guess_nsfw_info(image_path):
    """
    Guess NSFW content from an image with nsfw_model.

    :param image_path
    """
    try:
        model = predict.load_model(NSFW_MODEL)
        img_dict = predict.classify(model, image_path)[image_path]
        return (
            float(img_dict["porn"]),
            float(img_dict["hentai"]),
            float(img_dict["sexy"]),
        )
    except Exception as error:
        logger.error(error, exc_info=True)


def get_list_of_files(path):
    """
    Scan recursively for files.

    :param path: path
    """
    file_list = []
    for ext in EXTENSIONS:
        for i in glob.glob(os.path.join(path, "**", ext), recursive=True):
            file_list.append(i)
    return file_list


def check_image_list_integrity(image_list):
    """
    :param image_list: list of PIL.Image objects
    :raises InconsistentImageSizes
    """
    if len(image_list) < 2:
        return

    width, height = image_list[0].size
    logger.info(f"Checking image list integrity (first image: {width}*{height})")

    for image in image_list[1:]:
        tmp_width, tmp_height = image.size
        if abs(width - tmp_width) > 50 or abs(height - tmp_height) > 50:
            raise InconsistentImageSizes(f"{width}/{height}-{tmp_width}/{tmp_height}")


def is_episode(title):
    return re.search(r"s0[0-9]e[0-9][0-9]", title, flags=re.IGNORECASE) is not None


def is_sd_source(path):
    return any(sd_source in path.split("/")[-1].lower() for sd_source in SD_SOURCES)


def is_name_invalid(name):
    return any(invalid in name for invalid in INVALID_NAME_CHARS) or len(name) > 25


def is_timestamp(text):
    return convert_request_content(text) != text


def normalize_request_str(quote, lowercase=True):
    final = " ".join(clean_sub(quote).replace("\n", " ").split())
    if not lowercase:
        return final
    return final.lower()


def check_offensive_content(text):
    """
    :param text: text
    :raises exceptions.OffensiveWord
    """
    with open(OFFENSIVE_JSON) as words:
        if any(i in text.lower() for i in json.load(words)):
            raise OffensiveWord


def get_video_length(filename):
    """
    :param filename: filename
    :raises subprocess.TimeoutExpired
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            filename,
        ],
        stdout=subprocess.PIPE,
        timeout=30,
    )
    length = int(result.stdout.decode().replace("\n", "").split(".")[0])
    logger.info(f"Found length: {length}")
    return length


def extract_total_minute(text):
    """
    Extract total duration from a timestamp request string.

    :param text: comment string
    :raises exceptions.InvalidRequest
    """
    content = MINUTE_RE.findall(text)
    if not content:
        raise InvalidRequest(f"Invalid request: {text}")

    return content[0]


def clean_sub(text):
    """
    Remove unwanted characters from a subtitle string.

    :param text: text
    """
    cleaner = re.compile(r"<.*?>|🎶|♪")
    return re.sub(cleaner, "", text).replace(". . .", "...").strip()


def convert_request_content(content):
    """
    Convert a request string to a timestamp integer if necessary.

    :param content: request string
    """
    try:
        try:
            m, s = content.split(":")
            second = int(m) * 60 + int(s)
        except ValueError:
            h, m, s = content.split(":")
            second = (int(h) * 3600) + (int(m) * 60) + int(s)
        return second
    except ValueError:
        return content


def is_valid_timestamp_request(request_dict, movie_dict):
    """
    :param comment_dict: request dictionary
    :param movie_dict: movie dictionary
    :raises exceptions.InvalidSource
    :raises exceptions.InvalidRequest
    """
    # Ignore episodes for now
    if not movie_dict.get("runtime"):
        return

    runtime_movie = convert_request_content(movie_dict["runtime"])

    if runtime_movie == movie_dict["runtime"]:
        raise InvalidRequest(runtime_movie)

    runtime_request = convert_request_content(
        extract_total_minute(request_dict["comment"])
    )
    if abs(runtime_movie - runtime_request) > 2:
        raise DifferentSource(f"{runtime_movie}/{runtime_request}")

    logger.info("Valid timestamp request: {runtime_movie}/{runtime_request}")


def check_sub_matches(subtitle, subtitle_list, request_list):
    """
    :param subtitle: first srt.Subtitle object reference
    :param subtitle_list: list of srt.Subtitle objects
    :param request_list: list of request dictionaries
    """
    inc = 1
    hits = 1
    index_list = [subtitle.index - 1]
    while True:
        index_ = (subtitle.index + inc) - 1
        try:
            subtitle_ = subtitle_list[index_]
            if request_list[inc] == normalize_request_str(subtitle_.content):
                hits += 1
                inc += 1
                index_list.append(index_)
            else:
                break
        except IndexError:
            break

    if len(request_list) == len(index_list):
        logger.info(f"Perfect score: {hits}/{len(request_list)}")

    return index_list


def check_perfect_chain(request_list, subtitle_list):
    """
    Return a list of srt.Subtitle objects if more than one coincidences
    are found.

    :param request_list: list of request dictionaries
    :param subtitle_list: list of srt.Subtitle objects
    """
    request_list = [normalize_request_str(req) for req in request_list]
    hits = 0
    for subtitle in subtitle_list:
        if request_list[0] == normalize_request_str(subtitle.content):
            loop_hits = check_sub_matches(subtitle, subtitle_list, request_list)
            if len(loop_hits) > hits:
                hits = len(loop_hits)
                index_list = loop_hits

    if hits > 1:
        return [subtitle_list[index] for index in index_list]
    return []


def check_chain_integrity(request_list, chain_list):
    """
    Check if a list of requests strictly matchs a chain of subtitles.

    :param request_list: list of request strings
    :param chain_list: list of subtitle content strings
    :raises exceptions.InconsistentSubtitleChain
    """
    for og_request, sub_content in zip(request_list, chain_list):
        og_len = len(normalize_request_str(og_request))
        chain_len = len(normalize_request_str(sub_content))
        if abs(og_len - chain_len) > 2:
            raise InconsistentSubtitleChain(f"{og_len} - {chain_len}")


def get_subtitle(item={}, key="subtitle", path=None):
    """
    :param item: movie dictionary
    :param key: key from movie dictionary
    :param path: force reading from file path
    """
    with open(item.get(key) if not path else path, "r") as it:
        return list(srt.parse(it))


def get_hue_saturation_mean(image):
    """
    :param image: PIL.Image object
    """
    hsv = ImageStat.Stat(image.convert("HSV"))
    hue = hsv.mean[2]
    saturation = hsv.mean[1]
    return np.mean[hue, saturation]


def is_image_white(image):
    """
    :param image: PIL.Image object
    """
    img_array = np.array(image)
    return np.mean(img_array) > 120


def check_list_of_watched_plex():
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    movies = plex.history(accountID=PLEX_ACCOUNT_ID)
    return [movie.title for movie in movies]


def check_current_playing_plex():
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    return [playing.title for playing in plex.sessions()]


def get_collage(images, resize=True):
    """
    Create a collage from a list of images. Useful for poster collages and
    images with multiple subs. The resize boolean only works for posters.

    :param images: list of PIL.Image objects
    :param resize: resize all the images to 1200x1200 first
    """
    logger.info(f"Making collage for {len(images)} images")
    width, height = images[0].size
    new_images = [im.resize((width, height)) for im in images]
    row, col = POSSIBLES[str(len(images))]

    if resize:
        row, col = (3, 2)

    collage_width = row * width
    collage_height = col * height
    new_image = Image.new("RGB", (collage_width, collage_height))
    cursor = (0, 0)

    for image in new_images:
        new_image.paste(image, cursor)
        y = cursor[1]
        x = cursor[0] + width
        if cursor[0] >= (collage_width - width):
            y = cursor[1] + height
            x = 0
        cursor = (x, y)

    if resize:
        return new_image.resize((1200, 1200))

    if len(images) == 5:
        resized_new = new_image.resize((width, height))
        new_image1 = Image.new("RGB", (width, height * 2))
        new_image1.paste(resized_new, (0, 0))
        new_image1.paste(images[4], (0, height))
        return new_image1

    return new_image


def decorate_info(image, foreground, new_w, new_h):
    """
    :param image: PIL.Image object
    :param foreground: color tuple
    :param new_w: new width integer
    :param new_h: new height integer
    """
    height, width = image.size
    font = ImageFont.truetype(FONT, 37)
    font_foot = ImageFont.truetype(FONT, 33)

    draw = ImageDraw.Draw(image)
    text_h, text_w = draw.textsize(HEADER, font)
    draw.text((int(new_h * 1.75), 39), HEADER, fill=foreground, font=font)
    draw.text((int(new_h * 1.75), width - 98), FOOTER, fill=foreground, font=font_foot)
    return image


def get_poster_collage(movie_list):
    """
    Get a collage of posters from a list of dictionaries.

    :param movie_list: list of movie dictionaries
    """
    logger.info("Making collage of posters")
    movie_list = [
        item for item in movie_list if "Unknown" not in item.get("poster", "n/a")
    ]
    pick_four = random.sample(movie_list, 6)
    try:
        images = [url_to_pil(i.get("poster")) for i in pick_four]
    except:  # noqa
        logger.error("Error making the collage")
        return

    final = get_collage(images)
    width, height = final.size
    foreground, background = get_dominant_colors(final)

    new_w = int(height * 0.23)
    new_h = 50
    collage = ImageOps.expand(final, border=(new_h, int(new_w / 2)), fill=background)

    return decorate_info(collage, foreground, new_w, new_h)


def handle_kino_songs(song=None):
    """
    Handle kinosongs text file. If song is not None, append it to the
    file, otherwise return a random song from the list.

    :param song: song URL
    """
    Path(KINOSONGS).touch(exist_ok=True)

    if not song:
        with open(KINOSONGS) as kinosongs:
            songs = [song.replace("\n", "") for song in kinosongs.readlines()]
            try:
                return random.choice(songs)
            except IndexError:
                return

    with open(KINOSONGS, "a") as kinosongs:
        kinosongs.write(song + "\n")


def kino_log(log_path):
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s - %(module)s.%(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    rotable = handlers.TimedRotatingFileHandler(log_path, when="midnight")
    printable = logging.StreamHandler()

    rotable.setFormatter(formatter)
    printable.setFormatter(formatter)

    logger.addHandler(printable)
    logger.addHandler(rotable)

    return logger
