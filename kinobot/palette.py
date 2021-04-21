#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import io
import logging
from typing import Optional, List

import wand.image
from PIL import Image, ImageOps

from kinobot.cache import region
from kinobot.exceptions import NotEnoughColors

logger = logging.getLogger(__name__)


class Palette:
    """Class for Kinobot color palettes draw over PIL Image objects."""

    def __init__(
        self,
        image: Image.Image,
        dither: str = "floyd_steinberg",
        colorspace: Optional[str] = None,
        discriminator: Optional[str] = None,
    ):
        self.image = image
        self.discriminator = discriminator
        self.colorspace = colorspace
        self.dither = dither
        self.colors = []
        self.wand = None

    def draw(self, border: float = 0.015):
        """
        Append a nice palette to an image. Return the original image if something
        fails (not enough colors, b/w, etc.)

        :param border: border size
        """
        self._load_colors()

        if not self._clean_colors():
            logger.debug("Palette ignored")
            return

        w, h = self.image.size
        border = int(w * border)
        if float(w / h) > 2.1:
            border = border - int((w / h) * 4)

        new_w = int(w + (border * 2))
        div_palette = int(new_w / len(self.colors))
        bg = Image.new("RGB", (new_w, border), "white")

        next_ = 0

        for color in range(len(self.colors)):
            if color == 0:
                img_color = Image.new("RGB", (div_palette, border), self.colors[color])
                bg.paste(img_color, (0, 0))
                next_ += div_palette
            elif color == len(self.colors) - 1:
                leftover = int((w - (div_palette * (len(self.colors) - 1))) / 2)
                img_color = Image.new(
                    "RGB", (div_palette + leftover, border), self.colors[color]
                )
                bg.paste(img_color, (next_, 0))
                next_ += div_palette
            else:
                leftover = int((w - (div_palette * 9)) / 2)
                img_color = Image.new("RGB", (div_palette, border), self.colors[color])
                bg.paste(img_color, (next_, 0))
                next_ += div_palette

        bordered = ImageOps.expand(
            self.image, border=(border, border, border, 0), fill=self.colors[0]
        )
        bordered.paste(bg, (0, int(h)))

        logger.debug("Palette finished")
        self.image = bordered

    def _load_colors(self):
        if self.discriminator is not None:
            self.colors = self._get_colors_w_cache(self.discriminator)
        else:
            self.colors = self._get_colors()

    @property
    def hex_colors(self) -> List[str]:
        """List of hex colors from the generated palette.

        :rtype: List[str]
        """
        return ["#%02x%02x%02x" % color for color in self.colors]

    @region.cache_on_arguments()
    def _get_colors_w_cache(self, discriminator: str):
        logger.info("Loading colors with discriminator: %s", discriminator)
        return self._get_colors()

    def _get_colors(self):
        self._load_wand()

        self.wand.quantize(10, colorspace_type=self.colorspace, dither=self.dither)

        logger.info("Extracting colors (dither: %s)", self.dither)

        self.wand.unique_colors()

        pil_pixels = self._wand_to_pil(self.wand)

        self.wand.close()

        return list(pil_pixels.getdata())

    def _load_wand(self):
        """
        :param image: PIL.Image object
        """
        filelike = io.BytesIO()
        self.image.save(filelike, "JPEG")

        filelike.seek(0)

        self.wand = wand.image.Image(blob=filelike)

        filelike.close()

    def _clean_colors(self) -> bool:
        assert len(self.colors) > 1

        if len(self.colors) < 6:
            logger.debug("Not enough colors")
            return False

        # We can never know how many colors imagemagick will return
        # This loop checks wether a color is too white or not
        for color in range(5, len(self.colors)):
            hits = 0
            for tup in self.colors[color]:
                if tup > 160:
                    hits += 1
            if hits > 2:
                logger.debug("Removed white colors: %d", hits)
                self.colors = self.colors[:color]
                break

        return True

    @staticmethod
    def _wand_to_pil(wand_img):
        """
        :param wand_img: wand.image.Image object
        """
        # Using io.BytesIO; numpy arrays seem to fail with b/w images
        with Image.open(io.BytesIO(wand_img.make_blob("png"))).convert("RGB") as img:
            return img


class LegacyPalette(Palette):
    """Old-style palette class."""

    def draw(self, border: float = 0.95):
        """
        Append a palette (old style) to an image. Raise an exception if
        something fails (not enough colors, b/w, etc.)

        :raises exceptions.NotEnoughColors
        """
        self._load_colors()

        if len(self.colors) < 10:
            raise NotEnoughColors(
                f"Expected 10 colors, found {len(self.colors)}. Possible reasons: too "
                "dark/light image or black and white image."
            )

        width, height = self.image.size

        # calculate dimensions and generate the palette
        # get a nice-looking size for the palette based on aspect ratio
        divisor = (height / width) * 5.5
        height_palette = int(height / divisor)
        div_palette = int((width / len(self.colors)) * 0.99)
        off_palette = int(div_palette * border)

        bg = Image.new("RGB", (width - int(off_palette * 0.2), height_palette), "white")
        next_ = 0

        for color in range(len(self.colors)):
            if color == 0:
                img_color = Image.new(
                    "RGB", (int(div_palette * 0.95), height_palette), self.colors[color]
                )
                bg.paste(img_color, (0, 0))
                next_ += div_palette
            else:
                img_color = Image.new(
                    "RGB", (off_palette, height_palette), self.colors[color]
                )
                bg.paste(img_color, (next_, 0))

                next_ += div_palette

        palette_img = bg.resize((width, height_palette))

        # draw borders and append the palette

        # borders = int(width * 0.0075)
        borders = int(width * 0.0065)
        borders_total = (borders, borders, borders, height_palette + borders)

        bordered_original = ImageOps.expand(
            self.image, border=borders_total, fill="white"
        )
        bordered_palette = ImageOps.expand(
            palette_img, border=(0, borders), fill="white"
        )

        bordered_original.paste(bordered_palette, (borders, height))

        logger.debug("Palette finished")
        self.image = bordered_original
