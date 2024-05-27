#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import abc
import io
import logging
import tempfile
from typing import Dict, Union

from PIL import Image
import wand.image

logger = logging.getLogger(__name__)


class ColorSourceABC(abc.ABC):
    _config: Dict

    @abc.abstractmethod
    def get(self, image_path):
        raise NotImplementedError


class WandColorSource(ColorSourceABC):
    def __init__(
        self, color_count=5, dither="floyd_steinberg", colorspace=None, **kwargs
    ) -> None:
        self._color_count = color_count
        self._dither = dither
        self._colorspace = colorspace

    def get(self, image_path):
        with wand.image.Image(filename=image_path) as img:
            img.quantize(
                self._color_count, colorspace_type=self._colorspace, dither=self._dither
            )

            img.unique_colors()

            with Image.open(io.BytesIO(img.make_blob("png"))).convert("RGB") as pil_img:
                color_list = list(pil_img.getdata())

        return color_list


class CustomPalette:
    def __init__(self, color_handler_config=None, palette_height=33):
        self._c_config = color_handler_config
        self._palette_height = palette_height

    def draw(self, image: Union[str, Image.Image]):
        pil_, path = _get_pil_and_path(image)

        width, height = pil_.size

        palette_height = int(height * self._palette_height / 100)

        logger.debug("With and height: %s", pil_.size)
        logger.debug("Palette height: %s", palette_height)

        colors = WandColorSource(**self._c_config or {}).get(path)

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
