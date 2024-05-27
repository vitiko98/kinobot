#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import abc
import io
import tempfile
import logging
from typing import Dict, List, Optional, Union

from PIL import Image
from PIL import ImageOps
import wand.image

from kinobot.cache import region
from kinobot.exceptions import NotEnoughColors

logger = logging.getLogger(__name__)


class ColorSourceABC(abc.ABC):
    _config: Dict

    @abc.abstractmethod
    def get(self, image_path):
        raise NotImplementedError


class WandColorSource(ColorSourceABC):
    def __init__(
        self, color_count=10, dither="floyd_steinberg", colorspace=None, **kwargs
    ) -> None:
        self._color_count = color_count
        self._dither = dither
        self._colorspace = colorspace

    def get(self, image_path):
        with wand.image.Image(filename=image_path) as img:
            logger.debug("Quantizing %s", image_path)
            img.quantize(
                self._color_count, colorspace_type=self._colorspace, dither=self._dither  # type: ignore
            )
            logger.debug("Extracting unique colors")
            img.unique_colors()

            with Image.open(io.BytesIO(img.make_blob("png"))).convert("RGB") as pil_img:  # type: ignore
                color_list = list(pil_img.getdata())

        return color_list


_FLAGS_MAP = {
    "palette_color_count": "color_count",
    "palette_dither": "dither",
    "palette_colorspace": "colorspace",
}

_DRAW_MAP = {
    "palette_height": "palette_height",
    "palette_position": "position",
}


def draw_palette_from_config(image: Union[str, Image.Image], **config):
    c_source_config = {}
    draw_config = {}
    for key, val in _FLAGS_MAP.items():
        if config.get(key) is not None:
            c_source_config[val] = config[key]

    for key, val in _DRAW_MAP.items():
        if config.get(key) is not None:
            draw_config[val] = config[key]

    c_source = WandColorSource(**c_source_config)
    return draw_palette(image, color_handler=c_source, **draw_config)


def draw_palette(
    image: Union[str, Image.Image],
    color_handler=None,
    palette_height=33,
    position="bottom",
):
    pil_, path = _get_pil_and_path(image)

    width, height = pil_.size

    palette_height = int(height * abs(palette_height) / 100)

    logger.debug("With and height: %s", pil_.size)
    logger.debug("Palette height: %s", palette_height)

    colors = (color_handler or WandColorSource()).get(path)

    bg = Image.new("RGB", (width, palette_height), colors[-1])

    colors_width = int(width / len(colors))

    last_c = None
    for color in colors:
        color_img = Image.new("RGB", (colors_width, palette_height), color)
        if last_c is None:
            bg.paste(color_img, (0, 0))
            last_c = 0
        else:
            bg.paste(color_img, (last_c + colors_width, 0))
            last_c += colors_width

    final_img = Image.new("RGB", (width, height + bg.size[1]), colors[0])

    if position == "top":
        final_img.paste(pil_, (0, height))
        final_img.paste(bg, (0, 0))
    else:
        final_img.paste(pil_, (0, 0))
        final_img.paste(bg, (0, height))

    return final_img


def _get_pil_and_path(image: Union[str, Image.Image]):
    if isinstance(image, Image.Image):
        _, path = tempfile.mkstemp(prefix="custom_palette_", suffix=".png")
        image.save(path)
        logger.debug("Temp image saved: %s", path)
        return image, path
    else:
        pil_ = Image.open(image)
        return pil_, image


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
