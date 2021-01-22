#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import logging
import subprocess
import distro

from operator import itemgetter

from PIL import Image, ImageOps
from colorthief import ColorThief

from kinobot import MAGICK_SCRIPT

logger = logging.getLogger(__name__)


def get_colors(image):
    """
    Get a list of ten colors from MAGICK_SCRIPT (see kinobot/scripts folder).

    :param image: PIL.Image object
    """
    image.save("/tmp/tmp_palette.png")
    logger.debug("Using ImageMagick's color extraction method")

    output = (
        subprocess.check_output([MAGICK_SCRIPT, "/tmp/tmp_palette.png"])
        .decode()[:-1]
        .split("\n")
    )

    if "arch" in distro.linux_distribution(full_distribution_name=False):
        return [tuple([int(i) for i in color.split(".")]) for color in output]

    return [tuple([int(i) for i in color.split(",")]) for color in output]


def get_most_diff(saved_colors, new_colors):
    """
    :param saved_colors: list of previous colors
    :param new_colors: list of colors from slice
    """
    colors = []
    for new in new_colors:
        hits = 0
        for saved in saved_colors:
            if abs(new[0] - saved[0]) > 10:
                hits += 1
        colors.append({"color": new, "hits": hits})

    return sorted(colors, key=itemgetter("hits"), reverse=True)[0]


def get_colors_alt(image):
    """
    Alternative color extractor. This only works with a modified version of
    colorthief which takes an PIL.Image object as a parameter instead of
    a file.

    :param image: PIL.Image object
    """
    logger.debug("Using Kinobot's experimental color extraction method")

    width, height = image.size
    slices = int(width / 10)
    saved_colors = []

    for i in range(10):
        box = (i * slices, 0, slices + (i * slices), height)
        cropped = image.crop(box)
        thief = ColorThief(
            cropped,
        )
        if i == 0:
            principal = thief.get_color()
            saved_colors.append(principal)
        else:
            new_colors = thief.get_palette(color_count=100)
            new_color = get_most_diff(saved_colors, new_colors)
            if new_color is not None:
                saved_colors.append(new_color["color"])

    return saved_colors


def clean_colors(colors, tolerancy=2):
    """
    Remove "too white" colors from a list so the palette looks better.

    :param colors: colors list
    """
    logger.info("Checking palette list")
    if len(colors) < 6:
        logger.debug("Not enough colors")
        return
    # we can never know how many colors imagemagick will return
    # this loop checks wether a color is too white or not
    for color in range(5, len(colors)):
        hits = 0
        for tup in colors[color]:
            if tup > 165:
                hits += 1
        if hits > tolerancy:
            logger.debug(f"Removed white colors: {hits}")
            return colors[:color]

    logger.debug("Good palette")
    return colors


def get_palette_legacy(image, magick=True):
    """
    Append a palette (old style) to an image. Return the original image if
    something fails (not enough colors, b/w, etc.)

    :param image: PIL.Image object
    :param magick: use ImageMagick method to extract colors
    """
    width, height = image.size

    try:
        color_func = get_colors if magick else get_colors_alt
        colors = color_func(image)
    except Exception as error:
        logger.error(error, exc_info=True)
        return image

    palette = clean_colors(colors, tolerancy=2)

    if not palette:
        return image

    if len(palette) < 10:
        return image

    # calculate dimensions and generate the palette
    # get a nice-looking size for the palette based on aspect ratio
    divisor = (height / width) * 5.5
    height_palette = int(height / divisor)
    div_palette = int(width / len(palette))
    # off_palette = int(div_palette * 0.925)
    off_palette = int(div_palette * 0.95)

    # append colors
    bg = Image.new("RGB", (width - int(off_palette * 0.2), height_palette), "white")
    next_ = 0
    try:
        for color in range(len(palette)):
            if color == 0:
                img_color = Image.new(
                    "RGB", (int(div_palette * 0.95), height_palette), palette[color]
                )
                bg.paste(img_color, (0, 0))
                next_ += div_palette
            else:
                img_color = Image.new(
                    "RGB", (off_palette, height_palette), palette[color]
                )
                bg.paste(img_color, (next_, 0))
                next_ += div_palette
        palette_img = bg.resize((width, height_palette))

        # draw borders and append the palette

        # borders = int(width * 0.0075)
        borders = int(width * 0.0065)
        borders_total = (borders, borders, borders, height_palette + borders)

        bordered_original = ImageOps.expand(image, border=borders_total, fill="white")
        bordered_palette = ImageOps.expand(
            palette_img, border=(0, borders), fill="white"
        )

        bordered_original.paste(bordered_palette, (borders, height))

        return bordered_original

    except TypeError:
        return image


def get_palette(image, border=0.015, magick=True):
    """
    Append a nice palette to an image. Return the original image if something
    fails (not enough colors, b/w, etc.)

    :param image: PIL.Image object
    :param border: border size
    :param magick: use ImageMagick method to extract colors
    """
    try:
        color_func = get_colors if magick else get_colors_alt
        colors = color_func(image)
    except Exception as error:
        logger.error(error, exc_info=True)
        return image

    palette = clean_colors(colors)

    if not palette:
        return image

    logger.debug(palette)
    w, h = image.size
    border = int(w * border)
    if float(w / h) > 2.1:
        border = border - int((w / h) * 4)

    new_w = int(w + (border * 2))
    div_palette = int(new_w / len(palette))
    bg = Image.new("RGB", (new_w, border), "white")

    next_ = 0
    try:
        for color in range(len(palette)):
            if color == 0:
                img_color = Image.new("RGB", (div_palette, border), palette[color])
                bg.paste(img_color, (0, 0))
                next_ += div_palette
            elif color == len(palette) - 1:
                leftover = int((w - (div_palette * (len(palette) - 1))) / 2)
                img_color = Image.new(
                    "RGB", (div_palette + leftover, border), palette[color]
                )
                bg.paste(img_color, (next_, 0))
                next_ += div_palette
            else:
                leftover = int((w - (div_palette * 9)) / 2)
                img_color = Image.new("RGB", (div_palette, border), palette[color])
                bg.paste(img_color, (next_, 0))
                next_ += div_palette

        logger.debug(palette[0])
        # bordered = ImageOps.expand(
        #    image, border=(border, border, border, 0), fill=palette[0]
        # )
        bordered = ImageOps.expand(
            image, border=(border, border, border, 0), fill=palette[0]
        )
        bordered.paste(bg, (0, int(h)))

        return bordered

    except TypeError:
        return image
