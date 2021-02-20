#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

# I don't like hardcoded integers with image processing, but in this case I
# think by-hand numbers make the final result look better.

import logging
import os
import re
import json

from textwrap import wrap
from operator import itemgetter

import tmdbsimple as tmdb
import numpy as np
import requests

from colorthief import ColorThief
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from kinobot import FONTS, TMDB, FANART, KINOSTORIES
from kinobot.exceptions import MovieNotFound, ImageNotFound, InvalidRequest
from kinobot.utils import download_image, crop_image, truncate_long_text

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


def get_background(image, width=1080, height=1920, crop=True):
    main_image = image
    if crop:
        main_image = center_crop(image, height)

    blurred = crop_blurred_img(main_image.filter(ImageFilter.GaussianBlur(15)), height)
    enhancer = ImageEnhance.Brightness(blurred)
    blurred = enhancer.enhance(0.7)

    main_image.thumbnail((750, 750))
    # main_w, main_h = main_image.resize((750, 750)).size
    main_w, main_h = main_image.size
    # blurred.paste(main_image.resize((750, 750)), (int((width - main_w) / 2), 500))
    blurred.paste(main_image, (int((width - main_w) / 2), 500))

    return blurred


# A better way?
def scale_to_background(pil_image, size=1920):
    w, h = pil_image.size

    if h >= size:
        return pil_image

    size_2 = size + 200
    inc = 0.5
    while True:
        if size < h * inc < size_2:
            break
        inc += 0.1

    return pil_image.resize((int(w * inc), int(h * inc)))


def get_background_request(final_image, raw_image, width=1080, height=1920):
    main_image = scale_to_background(raw_image)

    blurred = crop_image(main_image.filter(ImageFilter.GaussianBlur(15)), 1080, 1920)
    enhancer = ImageEnhance.Brightness(blurred)
    blurred = enhancer.enhance(0.7)

    # main_image.thumbnail((825, 825))
    final_image = scale_to_background(final_image, 825)
    final_image.thumbnail((825, 925))
    # main_w, main_h = main_image.resize((750, 750)).size
    main_w, main_h = final_image.size
    # blurred.paste(main_image.resize((750, 750)), (int((width - main_w) / 2), 500))
    off_ = int((height - main_h) / 2)
    blurred.paste(final_image, (int((width - main_w) / 2), off_))

    return {
        "image": blurred,
        "thumbnail_top": off_,
        "thumbnail_bottom": off_ + final_image.size[1],
        "top_center": int(off_ / 2),
    }


def colorize_rating(image, width, height, dominant_color):
    """
    Colorize non-zero pixels from alpha image.
    """
    for x in range(width):
        for y in range(height):
            current_color = image.getpixel((x, y))
            if current_color == (0, 0, 0, 0):
                continue
            image.putpixel((x, y), dominant_color)


def homogenize_lines(split_quote):
    """
    Homogenize breakline lengths in order to guess the font size.

    :param split_quote: list of strings
    """
    max_len_quote = max([len(quote_) for quote_ in split_quote])

    for quote_ in split_quote:
        if len(quote_) < max_len_quote:
            yield quote_ + ("a" * (max_len_quote - len(quote_)))
        else:
            yield quote_


def draw_story_text(image, quote, color, offset=0.44, h_font_limit=100, align="left"):
    """
    :param image: PIL.Image object
    :param quote: quote string
    :param color: RGB/hex
    :param offset: width offset
    :param h_font_limit
    :param align: text align
    :raises InvalidRequest
    """
    if len(quote) > 75:
        raise InvalidRequest("Requested text is too long.")

    quote = "\n".join(wrap(" ".join(quote.split()), width=25))

    split_quote = quote.split("\n")

    tmp_text = "\n".join(list(homogenize_lines(split_quote)))

    split_len = len(split_quote)
    draw = ImageDraw.Draw(image)

    width, height = image.size
    font_size = 1
    font = ImageFont.truetype(FONT, font_size)

    while (font.getsize(tmp_text)[0] < 575 * split_len) and (
        font.getsize(tmp_text)[1] < h_font_limit
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
        align=align,
    )

    return image


def draw_story_text_request(image, quote, color, off_x, h_limit=100, line_len=25):
    """
    :param image: PIL.Image object
    :param quote: quote string
    :param color
    :param off_x: width offset
    :param h_limit: pixels limit from text height
    :param line_len: length of text to wrap
    :raises InvalidRequest
    """
    quote = truncate_long_text(quote, line_len * 3)

    quote = "\n".join(wrap(" ".join(quote.split()), width=line_len))

    split_quote = quote.split("\n")

    tmp_text = "\n".join(list(homogenize_lines(split_quote)))

    split_len = len(split_quote)
    draw = ImageDraw.Draw(image)

    width, height = image.size
    font_size = 1
    font = ImageFont.truetype(FONT, font_size)

    while (font.getsize(tmp_text)[0] < 575 * split_len) and (
        font.getsize(tmp_text)[1] < h_limit
    ):
        font_size += 1
        font = ImageFont.truetype(FONT, font_size)

    txt_w, txt_h = draw.textsize(quote, font)
    off_width = 1080 - (140 + txt_w)

    # result = off_height + txt_h + 20
    result = off_x + txt_h + 20
    draw.text(
        # (off_width, off_height),
        (off_width, off_x),
        quote,
        color,
        font=font,
        align="right",
    )

    return image, result


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


def get_story_request_image(image, raw_image, artist, title, author, colors):
    """
    :param image: main image
    :param raw_image: image without palette if present
    :param artist: artist
    :param title: title
    :param author: author
    :param colors: list of RGB colors or None
    """
    author = author.replace("_", " ").title()
    dominant_color = (255, 255, 255)

    if colors:
        if np.mean(colors[-1]) > 90:
            dominant_color = colors[-1]

    image = image.convert("RGB")
    bg_dict = get_background_request(image, raw_image)

    story = bg_dict["image"]

    image, new_off = draw_story_text_request(
        story,
        title,
        dominant_color,
        bg_dict["top_center"],
        90,
    )
    image, new_off = draw_story_text_request(
        story,
        "—" + artist,
        dominant_color,
        new_off,
        70,
        line_len=15,
    )

    distance = bg_dict["thumbnail_top"] - new_off

    return draw_story_text_request(
        story,
        f"Made with Kinobot",
        dominant_color,
        bg_dict["thumbnail_bottom"] + distance,
        70,
        line_len=15,
    )[0]


def search_movie(query, year, index=0):
    """
    :param query: query
    :param year: year
    :param index: movie result index to look into
    """
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
    """
    :param tmdb_id: ID from TMDB
    :param index: image result index to download
    """
    image_path = os.path.join(TEMP_STORY_DATA, f"{tmdb_id}-{index}.png")
    # Try to avoid extra recent API calls
    if os.path.isfile(image_path):
        logger.info("Found image on cache")
        return Image.open(image_path)

    logger.info(f"Getting image from Fanart for {tmdb_id} ID ({index} index)")
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
    Convert string to movie and year tuple.
    """
    match = re.findall(YEAR_RE, query)
    if not match or (len(query) == 4 and len(match) == 1):
        return query, None

    query = " ".join(query.replace(match[-1], "").split())
    return query, match[-1]


def get_story(query, username, stars, **kwargs):
    """
    :param query: query
    :param username: username
    :param stars: stars
    :param kwargs: **kwargs (review, movie_index, logo_index)
    """
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
