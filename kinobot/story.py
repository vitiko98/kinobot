#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import os
from textwrap import wrap
from typing import Optional

import numpy as np
from colorthief import ColorThief
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .constants import BACKDROPS_DIR, STARS_PATH, STORY_FONT
from .media import Movie
from .utils import download_image

logger = logging.getLogger(__name__)


_STARS = {
    0.5: (os.path.join(STARS_PATH, "half.png"), '"Peak Cringe"'),
    1.0: (os.path.join(STARS_PATH, "one.png"), '"Peak Cringe"'),
    1.5: (os.path.join(STARS_PATH, "onehalf.png"), '"Certified Cringe"'),
    2.0: (os.path.join(STARS_PATH, "two.png"), '"Certified Cringe"'),
    2.5: (os.path.join(STARS_PATH, "twohalf.png"), '"Borderline Cringe"'),
    3.0: (os.path.join(STARS_PATH, "three.png"), '"Borderline Kino"'),
    3.5: (os.path.join(STARS_PATH, "threehalf.png"), '"Certified Kino"'),
    4.0: (os.path.join(STARS_PATH, "four.png"), '"High Kino"'),
    4.5: (os.path.join(STARS_PATH, "fourhalf.png"), '"High Kino"'),
    5.0: (os.path.join(STARS_PATH, "five.png"), '"Peak Kino"'),
}


class Story:
    """Base class for Kinobot stories."""

    def __init__(
        self,
        media,
        image: Optional[str] = None,
        rating: float = 0,
        raw: Optional[Image.Image] = None,
    ):
        """
        :param media:
        :param image:
        :type image: Optional[str]
        :param rating:
        :type rating: float
        :raises urllib.error.HTTPError
        """
        if image is None:
            path = os.path.join(BACKDROPS_DIR, f"{media.type}_{media.id}.jpg")
            if not os.path.isfile(path):
                download_image(media.backdrop, path)
                logger.debug("Saved: %s", path)

            self.image = Image.open(path)
        else:
            self.image = Image.open(image)

        self._background = None
        self._dominant_color = (220, 220, 220)
        self._thumbnail_top = 0
        self._thumbnail_bottom = 0
        self._top_center = 0
        self._stars = None

        self.image = self.image.convert("RGB")
        self.rating = rating
        self.raw = raw

        self.media = media

    def _load_background(self, width=1080, height=1920):
        main_image = _scale_to_background(self.raw or self.image)

        blurred = _crop_image(
            main_image.filter(ImageFilter.GaussianBlur(15)), 1080, 1920
        )
        enhancer = ImageEnhance.Brightness(blurred)
        blurred = enhancer.enhance(0.7)

        final_image = _scale_to_background(self.image, 825)
        final_image.thumbnail((825, 925))
        main_w, main_h = final_image.size
        off_ = int((height - main_h) / 2)
        blurred.paste(final_image, (int((width - main_w) / 2), off_))

        logger.debug("Thumbnail off: %d", off_)

        self._background = blurred.convert("RGB")
        self._thumbnail_top = off_
        self._thumbnail_bottom = off_ + final_image.size[1]
        self._top_center = int(off_ / 2)

    def _load_dominant_color(self, image):
        color = ColorThief(image)
        guessed_color = color.get_color()
        logger.debug("Guessed color: %s", guessed_color)

        if np.mean(guessed_color) > 70:
            self._dominant_color = guessed_color
        else:
            logger.debug("Too dark color found")

    def _draw_text(self, text: str, off_x, h_limit=100, line_len=25) -> int:
        """
        :param text:
        :param off_x: width offset
        :param h_limit: pixels limit from text height
        :param line_len: length of text to wrap
        """
        quote = "\n".join(wrap(" ".join(text.split()), width=line_len))

        split_quote = quote.split("\n")

        tmp_text = "\n".join(list(_homogenize_lines(split_quote)))

        split_len = len(split_quote)
        draw = ImageDraw.Draw(self._background)

        font_size = 1
        font = ImageFont.truetype(STORY_FONT, font_size)

        while (font.getsize(tmp_text)[0] < 575 * split_len) and (
            font.getsize(tmp_text)[1] < h_limit
        ):
            font_size += 1
            font = ImageFont.truetype(STORY_FONT, font_size)

        txt_w, txt_h = draw.textsize(quote, font)
        off_width = 1080 - (140 + txt_w)

        # result = off_height + txt_h + 20
        result = off_x + txt_h + 20
        logger.debug("Text coordinates: %s", (off_width, off_x))

        draw.text(
            (off_width, off_x),
            quote,
            self._dominant_color,
            font=font,
            align="right",
        )

        self._background = self._background.convert("RGB")  # Consistency
        return result

    def _load_logo(self) -> bool:
        if self.media.logo is not None:

            logo = Image.open(self.media.logo)

            rgb_mean = np.mean(logo)
            if rgb_mean < 70:
                logger.debug("Too dark logo found: %s", rgb_mean)
                return False

            logger.debug("Cropping logo: %s", logo.size)
            logo = logo.crop(logo.getbbox())
            logger.debug("Result: %s", logo.size)
            self._load_dominant_color(logo)

            logo.thumbnail((600, 600))
            logo_w, logo_h = logo.size
            off_width = 1080 - (140 + logo_w)
            logger.debug("Logo off_width: %d", off_width)
            try:
                self._background.paste(
                    logo,
                    (off_width, self._top_center),
                    logo,
                )
                self._top_center = self._top_center + logo_h - 40  # fallback
                self._background = self._background.convert("RGB")
            except ValueError:  # Bad mask
                return False

            return True

        return False

    def _colorize_stars(self):
        """
        Colorize non-zero pixels from alpha image.
        """
        width, height = self._stars.size
        for x in range(width):
            for y in range(height):
                current_color = self._stars.getpixel((x, y))
                if current_color == (0, 0, 0, 0):
                    continue
                self._stars.putpixel((x, y), self._dominant_color)

    def _draw_stars(self, distance):
        self._stars = Image.open(_STARS[self.rating][0])
        self._stars = self._stars.crop(self._stars.getbbox())
        self._stars.thumbnail((600, 600))

        self._colorize_stars()

        star_w = self._stars.size[0]
        off_width = 1080 - (140 + star_w)
        logger.debug("Star off_width: %d", off_width)
        self._background.paste(
            self._stars,
            (off_width, self._thumbnail_bottom + distance),
            self._stars,
        )

    def get(self, path: str) -> str:
        self._load_background()

        if self._load_logo():
            new_off = self._top_center
        else:
            new_off = self._draw_text(self.media.title, self._top_center, 90)
            new_off = self._draw_text(f"-{self.media.year}", new_off, 70, line_len=15)

        logger.debug("Top center: %s", self._top_center)
        logger.debug("Final off: %d", new_off)
        distance = self._thumbnail_top - new_off

        logger.debug("Background: %s", self._background)
        logger.debug("Distance: %s", self._thumbnail_bottom + distance)

        if self.rating:
            self._draw_stars(distance)
        else:
            self._draw_text(
                "Made with Kinobot",
                self._thumbnail_bottom + distance - 30,
                70,
                line_len=15,
            )

        self._background.save(path)

        logger.info("Saved: %s", path)

        return path


class FallbackStory(Story):
    """An story class that always works."""

    def __init__(self):
        assert self
        super().__init__(Movie.from_query("Parasite"))


def _crop_image(pil_image, new_width=720, new_height=480):
    logger.info("New dimensions: %dx%d", new_width, new_height)
    width, height = pil_image.size

    left = (width - new_width) / 2
    right = (width + new_width) / 2
    top = (height - new_height) / 2
    bottom = (height + new_height) / 2

    return pil_image.crop((int(left), int(top), int(right), int(bottom)))


# A better way?
def _scale_to_background(pil_image, size=1920):
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


def _homogenize_lines(split_quote):
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
