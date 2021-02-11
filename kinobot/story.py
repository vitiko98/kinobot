#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

# I don't like hardcoded integers with image processing, but in this case I
# think by-hand numbers make the final result look better.

import logging
import os
import re
from textwrap import wrap

import tmdbsimple as tmdb
import requests
import json

import numpy as np

from colorthief import ColorThief
from operator import itemgetter
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from kinobot import FONTS, TMDB, FANART, KINOSTORIES
from kinobot.exceptions import MovieNotFound, ImageNotFound, InvalidRequest
from kinobot.utils import download_image

logger = logging.getLogger(__name__)

YEAR_RE = re.compile(r".*([1-3][0-9]{3})")
IMAGE_BASE = "https://image.tmdb.org/t/p/original"
TMDB_BASE = "https://www.themoviedb.org/movie"
FANART_BASE = "http://webservice.fanart.tv/v3/movies"
FONT = os.path.join(FONTS, "GothamMedium_1.ttf")
tmdb.API_KEY = TMDB

# /kinobot/kinobot/stars/*.png
STARS_PATH = os.path.join(KINOSTORIES, "stars")

TEMP_STORY_DATA = os.path.join(KINOSTORIES, "tmp")
os.makedirs(TEMP_STORY_DATA, exist_ok=True)


STARS = {
    1: (os.path.join(STARS_PATH, "one.png"), '"Peak Cringe"'),
    2: (os.path.join(STARS_PATH, "two.png"), '"Certified Cringe"'),
    3: (os.path.join(STARS_PATH, "three.png"), '"Certified Kino"'),
    4: (os.path.join(STARS_PATH, "four.png"), '"High Kino"'),
    5: (os.path.join(STARS_PATH, "five.png"), '"Peak Kino"'),
}


def crop_blurred_img(pil_image, height=736, new_width=1080):
    width, height = pil_image.size
    left = (width - new_width) / 2
    right = (width + new_width) / 2
    return pil_image.crop((int(left), 0, int(right), height))


def center_crop(img, height=1080):
    w, h = min(img.size), img.size[1]

    img_width, img_height = img.size
    left, right = (img_width - w) / 2, (img_width + w) / 2
    top, bottom = (img_height - h) / 2, (img_height + h) / 2
    left, top = round(max(0, left)), round(max(0, top))
    right, bottom = round(min(img_width - 0, right)), round(min(img_height - 0, bottom))
    return img.crop((left, top, right, bottom)).resize((height, height))


def get_background(image, width=1080, height=1920):
    main_image = center_crop(image, height)

    blurred = crop_blurred_img(main_image.filter(ImageFilter.GaussianBlur(15)), height)
    enhancer = ImageEnhance.Brightness(blurred)
    blurred = enhancer.enhance(0.7)

    main_w, main_h = main_image.resize((750, 750)).size
    blurred.paste(main_image.resize((750, 750)), (int((width - main_w) / 2), 500))

    return blurred


def colorize_rating(image, width, height, dominant_color):
    for x in range(width):
        for y in range(height):
            current_color = image.getpixel((x, y))
            if current_color == (0, 0, 0, 0):
                continue
            image.putpixel((x, y), dominant_color)


def draw_story_text(pil_image, quote, color, offset=0.44, height_font_limit=100):
    """
    :param pil_image: PIL.Image object
    :param quote: quote string
    :param color: RGB/hex
    :param offset: width offset
    :param height_font_limit
    :raises InvalidRequest
    """
    if len(quote) > 75:
        raise InvalidRequest("Requested text is too long.")

    quote = "\n".join(wrap(" ".join(quote.split()), width=25))

    split_quote = quote.split("\n")

    # Homogenize breakline lengths in order to guess the font size
    max_len_quote = max([len(quote_) for quote_ in split_quote])

    tmp_text = []
    for quote_ in split_quote:
        if len(quote_) < max_len_quote:
            tmp_text.append(quote_ + ("a" * (max_len_quote - len(quote_))))
        else:
            tmp_text.append(quote_)

    tmp_text = "\n".join(tmp_text)

    split_len = len(split_quote)
    draw = ImageDraw.Draw(pil_image)

    width, height = pil_image.size
    font_size = 1
    font = ImageFont.truetype(FONT, font_size)

    while (font.getsize(tmp_text)[0] < 575 * split_len) and (
        font.getsize(tmp_text)[1] < height_font_limit
    ):
        font_size += 1
        font = ImageFont.truetype(FONT, font_size)

    off = width * offset
    txt_w, txt_h = draw.textsize(quote, font)

    draw.text(
        ((width - txt_w) / 2, height - txt_h - off),
        quote,
        color,
        font=font,
        align="left",
    )

    return pil_image


def test_transparency_mask(image):
    """
    :raises ValueError
    """
    white = Image.new(size=(100, 100), mode="RGB")
    white.paste(image, (0, 0), image)


def get_story_image(image, logo, rating, name, review):
    """
    :param image: main PIL.Image
    :param logo: logo PIL.Image or str
    :param rating: rating int (1-5)
    :param name: name string
    :param review: review string or None
    """
    try:
        review = review or STARS[rating][1]

        if not review.startswith('"') or not review.endswith('"'):
            review = f'"{review}"'

        rating = Image.open(STARS[rating][0])
    except KeyError:
        raise InvalidRequest("Invalid stars number (choose between 1-5)")

    name = "—" + name
    width, height = rating.size

    dominant_color = (255, 255, 255)
    rating.thumbnail((550, 550))

    if not isinstance(logo, str):
        colorthief_ = ColorThief(logo)
        guessed_color = colorthief_.get_color()
        if np.mean(guessed_color) > 70:
            dominant_color = guessed_color
        else:
            dominant_color = (220, 220, 220)

    colorize_rating(rating, width, height, dominant_color)

    image = image.convert("RGB")
    story = get_background(image)

    if not isinstance(logo, str):
        logo.thumbnail((550, 550))
        story.paste(
            logo,
            (int((story.size[0] - logo.size[0]) / 2), int((585 - logo.size[1]) / 2)),
            logo,
        )
    else:
        draw_story_text(story, logo, dominant_color, 1.5, 75)

    story.paste(rating, (int((story.size[0] - rating.size[0]) / 2), 1525), rating)

    rated = draw_story_text(story, name, dominant_color, 0.2, 50)

    return draw_story_text(rated, review, dominant_color)


def search_movie(query, year, index=0):
    logger.info(f"Searching movie: {query} ({year}) ({index} index)")
    search = tmdb.Search()
    search.movie(query=query, year=year)

    if not search.results:
        raise MovieNotFound(f"Movie not found in TMDB: {query}")

    movies = sorted(
        [result for result in search.results],
        key=itemgetter("vote_count"),
        reverse=True,
    )

    movie_ = movies[index]
    if not movie_.get("backdrop_path"):
        raise ImageNotFound(
            "This movie doesn't have any images available. Contribute "
            "uploading a backdrop yourself and try again later: "
            f"{TMDB_BASE}/{movie_['id']}."
        )

    image = f"{IMAGE_BASE}/{movie_['backdrop_path']}"

    path = os.path.join(TEMP_STORY_DATA, f"{image.split('/')[-1]}.jpg")
    # Avoid extra recent downloads
    if os.path.isfile(path):
        image = Image.open(path)
    else:
        image = Image.open(download_image(image, path))

    logger.info("Ok")
    return {
        "title": movie_["title"],
        "tmdb_id": movie_["id"],
        "image": image,
    }


def get_fanart_logo(tmdb_id, index=0):
    image_path = os.path.join(TEMP_STORY_DATA, f"{tmdb_id}-{index}.png")
    # Try to avoid extra recent API calls
    if os.path.isfile(image_path):
        logger.info("Found image on cache")
        return Image.open(image_path)

    logger.info("Getting image from Fanart for {tmdb_id} ID ({index} index)")
    r = requests.get(f"{FANART_BASE}/{tmdb_id}", params={"api_key": FANART}, timeout=10)
    r.raise_for_status()

    result = json.loads(r.content)
    logos = result.get("hdmovielogo")
    if not logos:
        logos = result.get("movielogo")

    try:
        if not index:
            logo = [logo.get("url") for logo in logos if logo.get("lang") == "en"][0]
            return Image.open(download_image(logo, image_path))

        return Image.open(download_image(logos[index].get("url"), image_path))
    except (TypeError, IndexError) as error:
        raise ImageNotFound(f"{type(error).__name__} raised trying to get movie logo.")


def smart_search(query):
    """
    Convert a string to movie and year tuple.
    """
    match = re.findall(YEAR_RE, query)
    if not match or (len(query) == 4 and len(match) == 1):
        return query, None

    query = " ".join(query.replace(match[-1], "").split())
    return query, match[-1]


def get_story(query, username, stars, **kwargs):
    movie, year = smart_search(query)
    movie = search_movie(movie, year, kwargs.get("movie_index", 0))
    try:
        index = kwargs.get("logo_index", 0)
        while True:
            try:
                logo = get_fanart_logo(movie["tmdb_id"], index)
                test_transparency_mask(logo)
                break
            except ValueError:
                logger.info("Bad mask. Falling back")
                index += 1

            if index > 1:
                raise ImageNotFound

    except (ImageNotFound, requests.exceptions.HTTPError):
        logo = movie["title"].upper()

    return get_story_image(movie["image"], logo, stars, username, kwargs.get("review"))
