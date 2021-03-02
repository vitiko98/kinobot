#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import glob
import io
import json
import urllib
import logging
import os
import random
import re
import subprocess
import sys

import logging.handlers as handlers
from pathlib import Path

import numpy as np
import wand.image
import requests
import srt
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat
from ripgrepy import Ripgrepy

from kinobot import (
    FONTS,
    RANDOMORG,
    FACEBOOK,
    TMDB,
    FACEBOOK_TV,
    FACEBOOK_MUSIC,
    FANART,
    NSFW_MODEL,
    FILM_COLLECTION,
    KINOSONGS,
    OFFENSIVE_JSON,
)
from kinobot.exceptions import (
    InconsistentImageSizes,
    InconsistentSubtitleChain,
    InvalidRequest,
    DifferentSource,
    NSFWContent,
    OffensiveWord,
    SubtitlesNotFound,
)

FONT = os.path.join(FONTS, "NotoSansCJK-Regular.ttc")

POSSIBLES = {
    "1": (1, 1),
    "2": (1, 2),
    "3": (1, 3),
    "4": (1, 4),
    "5": (2, 2),
    "6": (2, 3),
}

EXTENSIONS = ("*.mkv", "*.mp4", "*.avi", "*.m4v")
SD_SOURCES = ("dvd", "480", "xvid", "divx", "vhs")
POPULAR = "00 01 02 03 05 07 09 10 12 13 15 16 17 18 19 20 21 22 23 34"
RANDOMORG_BASE = "https://api.random.org/json-rpc/2/invoke"
HEADER = "The Certified Kino Bot Collection"
FOOTER = "kino.caretas.club"
MINUTE_RE = re.compile(r"[^[]*\{([^]]*)\}")
ALT_TITLE = re.compile(r"[^[]*\<([^]]*)\>")
ID_RE = re.compile(r"ID:\ (.*?);")
USER_RE = re.compile(r"user:\ (.*?);")
PUNCT_RE = re.compile(r"^([a-z])|[\.|\?|\!]\s*([a-z])|\s+([a-z])(?=\.)")
CLEAN_QUOTE_RE = re.compile(r"\"|^\'{1,}|\.$|\.\"$|\.\'$|\'{1,}$")


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
    response.raise_for_status()
    response.raw.decode_content = True
    return Image.open(response.raw)


def download_image(url, path):
    """
    Download an image to filesystem from URL. This is used for stories in
    order to avoid extra recent downloads and API calls.
    """
    urllib.request.urlretrieve(url, path)
    return path


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


def check_nsfw(image_list):
    """
    :param image_list: list of image paths
    """
    # Painfully slow importing time
    from nsfw_detector import predict

    logger.info("Checking for NSFW content")
    for image in image_list:
        try:
            model = predict.load_model(NSFW_MODEL)
            img_dict = predict.classify(model, image)[image]
            nsfw_tuple = (
                float(img_dict["porn"]),
                float(img_dict["hentai"]),
                float(img_dict["sexy"]),
            )
        except Exception as error:
            logger.error(error, exc_info=True)
            raise NSFWContent("Error guessing NSFW")

        logger.info(nsfw_tuple)
        if any(guessed > 0.2 for guessed in nsfw_tuple):
            raise NSFWContent("NSFW guessed from %s: %s", image, nsfw_tuple)


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
        if abs(width - tmp_width) > 400 or abs(height - tmp_height) > 400:
            raise InconsistentImageSizes(
                "Image sizes are inconsistent, so a collage should not be "
                f"made: {width}/{height}:{tmp_width}/{tmp_height}. "
                "This incident will be reviewed."
            )


def clear_exception_sensitive_data(exc_str):
    """
    Clear sensitive data from exceptions in case of leak (Facebook or Discord
    replies).
    """
    for sensitive in (FACEBOOK, FACEBOOK_TV, FACEBOOK_MUSIC, TMDB, FANART):
        exc_str = exc_str.replace(sensitive, "REDACTED")

    return exc_str


def get_rg_pattern(text):
    """
    Generate a punctuation-insensitive regex for ripgrep.
    """
    after_word = r"(\s|\W|$|(\W\s))"
    pattern = r"(^|\s|\W)"
    for word in text.split():
        word = re.sub(r"\W", "", word)
        pattern = pattern + word + after_word

    return pattern


def search_line_matches(path, query):
    """
    :param path: path of subtitles directory
    :param query: ripgrep regex query
    """
    query = get_rg_pattern(query)
    # rg = Ripgrepy(fr"(\s|\W){query}(\s|\W|$)", path)
    rg = Ripgrepy(query, path)
    quote_list = rg.i().json().run().as_dict

    for quote in quote_list:
        path = quote["data"]["path"]["text"]
        if not path.endswith(".en.srt"):
            continue

        submatches = [sub["match"]["text"] for sub in quote["data"]["submatches"]]

        yield {
            "movie": os.path.abspath(path),
            "line": quote["data"]["lines"]["text"],
            "submatches": submatches,
            "re_pattern": query,
        }


def is_episode(title):
    return re.search(r"s[0-9][0-9]e[0-9][0-9]", title, flags=re.IGNORECASE) is not None


def is_sd_source(path):
    return any(sd_source in path.split("/")[-1].lower() for sd_source in SD_SOURCES)


def is_timestamp(text):
    return convert_request_content(text) != text


def get_id_from_discord(text, user=False):
    return re.search(ID_RE if not user else USER_RE, text).group(1)


def truncate_long_text(text, text_len=75):
    return (text[:text_len] + "...") if len(text) > text_len else text


def uppercase(matchobj):
    return matchobj.group(0).upper()


def fix_punctuation(text):
    return re.sub(PUNCT_RE, uppercase, text)


def extract_alt_title(text):
    content = ALT_TITLE.findall(text)
    if content:
        return content[0]


def normalize_to_quote(text):
    return " ".join(re.sub(CLEAN_QUOTE_RE, "", text).split())


def parse_arbitrary_flag(flag, text):
    """
    :param flag: name of the flag
    :param text: complete command string
    """
    try:
        found = [flag_ for flag_ in text.split() if f"--{flag}=" in flag_][0]
    except IndexError:
        return

    return found.replace(f"--{flag}=", "").strip()


def is_parallel(text):
    """
    :param text: complete comment string
    :raises exceptions.InvalidRequest
    """
    comment = text.replace("!parallel", "")
    parallels = [" ".join(movie.split()) for movie in comment.split("|")]

    if len(parallels) > 4:
        raise InvalidRequest("Expected less than 5 separators, found {len(parallels)}.")

    if 1 < len(parallels) < 5:
        return parallels


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
            raise OffensiveWord(
                "Offensive word found. If this is a Facebook requests, "
                "you'll be blocked."
            )


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
        raise InvalidRequest("Expected {TOTAL DURATION} variable.")

    return content[0]


def clean_sub(text):
    """
    Remove unwanted characters from a subtitle string.

    :param text: text
    """
    cleaner = re.compile(r"<.*?>|🎶|♪")
    return re.sub(cleaner, "", text).replace(". . .", "...").strip()


def convert_request_content(content, return_tuple=False):
    """
    Convert a request string to a timestamp or tuple (s, ms) if necessary.

    :param content: request string
    """
    content_split = content.split(".")
    timestamp = content_split[0]
    milli = content_split[-1]

    try:
        try:
            m, s = timestamp.split(":")
            second = int(m) * 60 + int(s)
        except ValueError:
            h, m, s = timestamp.split(":")
            second = (int(h) * 3600) + (int(m) * 60) + int(s)

        try:
            milli = int(milli)
            if not (50 < milli < 999):
                raise InvalidRequest(
                    "Invalid (>999) or trivial (<50) milliseconds "
                    f"value found: {milli}."
                )
        except ValueError:
            milli = 0

        if return_tuple:
            return second, milli

        return second
    except ValueError:
        return content


def is_valid_timestamp_request(request_dict, movie_dict):
    """
    :param comment_dict: request dictionary
    :param movie_dict: movie/episode dictionary
    :raises exceptions.InvalidSource
    :raises exceptions.InvalidRequest
    """
    runtime_movie = convert_request_content(movie_dict["runtime"])

    if runtime_movie == movie_dict["runtime"]:
        raise InvalidRequest("String found from timestamp request.")

    runtime_request = convert_request_content(
        extract_total_minute(request_dict["comment"])
    )
    if abs(runtime_movie - runtime_request) > 2:
        raise DifferentSource(
            "Request and Bot sources are not the same: "
            f"{runtime_movie}/{runtime_request}."
        )

    logger.info(f"Valid timestamp request: {runtime_movie}/{runtime_request}")


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
    try:
        with open(item.get(key) if not path else path, "r") as it:
            return list(srt.parse(it))
    except FileNotFoundError:
        raise SubtitlesNotFound("Subtitles not found. Please report this to the admin.")


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


def get_collage(images, resize=True, parallel=False):
    """
    Create a collage from a list of images. Useful for poster collages and
    images with multiple subs. The resize boolean only works for posters.

    :param images: list of PIL.Image objects
    :param resize: resize all the images to 1200x1200 first
    :param parallel: don't homogenize images
    """
    logger.info(f"Making collage for {len(images)} images")

    new_images = images
    if not parallel:
        new_images = homogenize_images(images)

    width, height = new_images[0].size
    #    new_images = [im.resize((width, height)) for im in images]

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


def crop_image(pil_image, new_width=720, new_height=480):
    logger.info(f"New dimensions: {new_width}, {new_height}")
    width, height = pil_image.size

    left = (width - new_width) / 2
    right = (width + new_width) / 2
    top = (height - new_height) / 2
    bottom = (height + new_height) / 2

    return pil_image.crop((int(left), int(top), int(right), int(bottom)))


def thumbnail_images(images):
    """
    :param images: list of PIL.Image objects
    """
    sizes = [image.size for image in images]

    for image in images:
        if image.size != min(sizes):
            image.thumbnail(min(sizes))
        yield image


def homogenize_images(images):
    """
    :param images: list of PIL.Image objects
    """
    images = list(thumbnail_images(images))

    first_min = min([image.size for image in images], key=lambda t: t[0])
    second_min = min([image.size for image in images], key=lambda t: t[1])

    return [crop_image(image, first_min[0], second_min[1]) for image in images]


def wand_to_pil(wand_img):
    """
    :param wand_img: wand.image.Image object
    """
    # Using io.BytesIO; numpy arrays seem to fail with b/w images
    return Image.open(io.BytesIO(wand_img.make_blob("png"))).convert("RGB")


def pil_to_wand(image):
    """
    :param image: PIL.Image object
    """
    filelike = io.BytesIO()
    image.save(filelike, "JPEG")
    filelike.seek(0)
    magick = wand.image.Image(blob=filelike)
    filelike.close()
    return magick


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


def check_directory():
    if not os.path.isdir(FILM_COLLECTION):
        sys.exit(f"Collection not mounted: {FILM_COLLECTION}")


def kino_log(log_path):
    """
    :param log_path: path to log file (append mode)
    """
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
