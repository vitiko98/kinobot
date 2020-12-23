#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import logging
import subprocess

from PIL import Image, ImageOps

from kinobot.config import MAGICK_SCRIPT

logger = logging.getLogger(__name__)


def get_colors(image, arch_linux=False):
    """
    Get a list of ten colors from MAGICK_SCRIPT (see kinobot/scripts folder).

    :param image: PIL.Image object
    :param arch_linux: Arch Linux compatibility
    """
    image.save("/tmp/tmp_palette.png")

    output = (
        subprocess.check_output([MAGICK_SCRIPT, "/tmp/tmp_palette.png"])
        .decode()[:-1]
        .split("\n")
    )

    if arch_linux:
        colors = []
        for i in output:
            new = [int(new_color.split(".")[0]) for new_color in i.split(",")]
            colors.append(tuple(new))
        return colors

    return [tuple([int(i) for i in color.split(",")]) for color in output]


def get_colors_arch(image):
    """
    Get a list of ten colors from MAGICK_SCRIPT (see kinobot/scripts folder)
    (Arch Linux variant)

    :param image: PIL.Image object
    """
    image.save("/tmp/tmp_palette.png")
    output = (
        subprocess.check_output([MAGICK_SCRIPT, "/tmp/tmp_palette.png"])
        .decode()[:-1]
        .split("\n")
    )
    colors = []
    for i in output:
        new = [int(new_color.split(".")[0]) for new_color in i.split(",")]
        colors.append(tuple(new))
    return colors


def clean_colors(colors):
    """
    Remove "too white" colors from a list so the palette looks better.

    :param colors: colors list
    """
    logger.info("Checking palette list...")
    if len(colors) < 6:
        return
    # we can never know how many colors imagemagick will return
    # this loop checks wether a color is too white or not
    for color in range(len(colors)):
        if color < 5:
            continue
        hits = 0
        for tup in colors[color]:
            if tup > 175:
                hits += 1
        if hits > 2:
            return colors[:color]
        logger.info(f"hits for color {color + 1}: {hits}")
    return colors


def get_palette_legacy(image):
    """
    Append a palette (old style) to an image. Return the original image if
    something fails (not enough colors, b/w, etc.)

    :param image: PIL.Image object
    """
    width, height = image.size

    try:
        colors = get_colors(image)
    except ValueError:
        return image

    palette = clean_colors(colors)

    if not palette:
        return image

    if len(palette) < 8:
        return image

    logger.info(f"Palette colors: {', '.join(palette)}")
    # calculate dimensions and generate the palette
    # get a nice-looking size for the palette based on aspect ratio
    divisor = (height / width) * 5.5
    height_palette = int(height / divisor)
    div_palette = int(width / len(palette))
    off_palette = int(div_palette * 0.925)

    # append colors
    bg = Image.new("RGB", (width - int(off_palette * 0.2), height_palette), "white")
    next_ = 0
    try:
        for color in enumerate(palette):
            if color == 0:
                img_color = Image.new(
                    "RGB", (int(div_palette * 0.925), height_palette), palette[color]
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

        borders = int(width * 0.0075)
        borders_total = (borders, borders, borders, height_palette + borders)

        bordered_original = ImageOps.expand(image, border=borders_total, fill="white")
        bordered_palette = ImageOps.expand(
            palette_img, border=(0, borders), fill="white"
        )

        bordered_original.paste(bordered_palette, (borders, height))

        return bordered_original

    except TypeError:
        return image


def get_palette(image):
    """
    Append a nice palette to an image. Return the original image if something
    fails (not enough colors, b/w, etc.)

    :param image: PIL.Image object
    """
    try:
        colors = get_colors(image)
    except ValueError:
        return image

    palette = clean_colors(colors)

    if not palette:
        return image

    logger.info(f"Palette colors: {', '.join(palette)}")
    w, h = image.size
    border = int(w * 0.03)
    if float(w / h) > 2.1:
        border = border - int((w / h) * 4)

    new_w = int(w + (border * 2))
    div_palette = int(new_w / len(palette))
    bg = Image.new("RGB", (new_w, border), "white")

    next_ = 0
    try:
        for color in enumerate(palette):
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

        bordered = ImageOps.expand(
            image, border=(border, border, border, 0), fill=palette[0]
        )
        bordered.paste(bg, (0, int(h)))

        return bordered

    except TypeError:
        return image
