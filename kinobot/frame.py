#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import os
import re
import subprocess
import textwrap

from tempfile import gettempdir
import cv2
import numpy as np

from dogpile.cache import make_region
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat
from pymediainfo import MediaInfo

from kinobot.palette import get_palette
from kinobot.utils import (
    clean_sub,
    check_offensive_content,
    get_cached_image,
    cache_image,
    wand_to_pil,
    pil_to_wand,
)
from kinobot import FONTS, CACHE_DIR

CACHE_PATH = os.path.join(CACHE_DIR, "dar.db")

FONT = os.path.join(FONTS, "helvetica.ttf")
FONT_OBLIQUE = os.path.join(FONTS, "Helvetica-Oblique.ttf")

REGION = make_region().configure(
    "dogpile.cache.dbm",
    arguments={"filename": CACHE_PATH},
)

logger = logging.getLogger(__name__)


def is_bw(pil_image):
    """
    Guess if an image is B/W.

    :param pil_image: PIL.Image object
    """
    hsv = ImageStat.Stat(pil_image.convert("HSV"))
    return hsv.mean[1] < 35


def fix_web_source(pil_image):
    """
    Remove leftovers from trim() for web sources.

    :param pil_image: PIL.Image object
    """
    logger.info("Cropping WEB source")
    width, height = pil_image.size
    off = int(height * 0.09)

    return pil_image.crop((0, off, width, height - off))


def cv2_to_pil(cv2_array):
    """
    Convert an array to a PIL.Image object.

    :param cv2_array: image array from cv2
    """
    image = cv2.cvtColor(cv2_array, cv2.COLOR_BGR2RGB)
    return Image.fromarray(image)


def wand_trim(pil_image):
    """
    Trim black borders from an image with ImageMagick's algorithm. This method
    seems to be more effective than PIL's but more resource intensive.

    :param pil_image: PIL.Image object
    """
    wand_img = pil_to_wand(pil_image)
    wand_img.trim(color="black", fuzz=20.0, percent_background=0.2)

    return wand_to_pil(wand_img)


def pil_trim(pil_image):
    """
    Trim black borders from an image.

    :param pil_image: PIL.Image object
    """
    bg = Image.new(pil_image.mode, pil_image.size, pil_image.getpixel((0, 0)))
    diff = ImageChops.difference(pil_image, bg)
    diff = ImageChops.add(diff, diff)
    bbox = diff.getbbox()

    if not bbox:
        return pil_image

    return pil_image.crop(bbox)


def remove_lateral_cv2(cv2_image):
    """
    :param cv2_image: cv2 image array
    """
    h, w, d = cv2_image.shape

    for i in range(w):
        if np.mean(cv2_image[:, i, :]) > 1.7:
            break

    for j in range(w - 1, 0, -1):
        if np.mean(cv2_image[:, j, :]) > 1.7:
            break

    return cv2_image[:, i : j + 1, :].copy()


def cv2_trim(cv2_image):
    """
    Remove black borders from a cv2 image array.

    :param cv2_image: cv2 image array
    """
    logger.info("Trying to remove black borders with cv2")
    og_w, og_h = cv2_image.shape[1], cv2_image.shape[0]
    og_quotient = og_w / og_h

    first_img = remove_lateral_cv2(cv2_image)

    tmp_img = cv2.transpose(first_img)
    tmp_img = cv2.flip(tmp_img, flipCode=1)

    final = remove_lateral_cv2(tmp_img)

    out = cv2.transpose(final)

    final_img = cv2.flip(out, flipCode=0)

    new_w, new_h = final_img.shape[1], final_img.shape[0]
    new_quotient = new_w / new_h

    if abs(new_quotient - og_quotient) > 0.9:
        logger.info(f"Possible bad quotient found: {og_quotient}:{new_quotient}")
        return cv2_image

    width_percent = (100 / og_w) * new_w
    height_percent = (100 / og_h) * new_h

    if any(percent <= 65 for percent in (width_percent, height_percent)):
        logger.info(f"Possible bad trim found: {width_percent}%:{height_percent}%")
        return cv2_image

    return final_img


def get_ffprobe_dar(path):
    """
    Get Display Aspect Ratio from ffprobe (Faster than MediaInfo but
    not as reliable).

    :param path: video path
    """
    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, timeout=60)
    return json.loads(result.stdout)["streams"][0]["display_aspect_ratio"].split(":")


@REGION.cache_on_arguments()
def get_dar(path):
    """
    Get Display Aspect Ratio from file.

    :param path: path
    """
    try:
        logger.info("Using ffprobe")
        d_width, d_height = get_ffprobe_dar(path)
        display_aspect_ratio = float(d_width) / float(d_height)
    except:  # noqa
        logger.info("ffprobe failed. Using mediainfo")
        media_info = MediaInfo.parse(path, output="JSON")
        display_aspect_ratio = float(
            json.loads(media_info)["media"]["track"][1]["DisplayAspectRatio"]
        )
    logger.info(f"Extracted DAR: {display_aspect_ratio}")
    return display_aspect_ratio


def prettify_aspect(pil_image):
    """
    Crop a image if is too wide or too square as it doesn't look good on
    Facebook. Very anti-kino, isn't it? But let's don't kill the reach.

    :param pil_image: PIL.Image object
    """
    width, height = pil_image.size
    quotient = width / height

    if quotient <= 1.4:
        logger.info(f"Cropping too square image ({quotient})")
        off = int(height * 0.133)

        return pil_image.crop((0, off, width, height - off))

    if quotient <= 2.25:
        return pil_image

    logger.info(f"Cropping too wide image ({quotient})")

    new_width = width * 0.85
    left = (width - new_width) / 2
    right = (width + new_width) / 2
    bottom = height

    return pil_image.crop((int(left), 0, int(right), bottom))


def trim(pil_image):
    """
    Remove black borders from WEB sources if present.

    :param pil_image: PIL.Image object
    :raises exceptions.InconsistentImageSizes
    """
    og_w, og_h = pil_image.size
    og_quotient = int((og_w / og_h) * 100)

    trim_ = pil_trim(pil_image)
    new_w, new_h = trim_.size
    new_quotient = int((new_w / new_h) * 100)
    trim_result = abs(og_quotient - new_quotient)
    logger.info(f"Trim result: {trim_result}")

    if trim_result > 100 or trim_result < 10:
        logger.info("Possible bad trim or normal image found")
        return pil_image

    if abs(og_w - new_w) > 5 or abs(og_h - new_h) > 5:
        logger.info("The image was modified")

    return prettify_aspect(trim_)


def fix_dar(path, frame, display_aspect_ratio=None):
    """
    Fix aspect ratio from cv2 image array.

    :param path: path
    :param frame: cv2 image array
    :param display_aspect_ratio
    """
    if not display_aspect_ratio:
        display_aspect_ratio = get_dar(path)

    logger.info(f"Found DAR: {display_aspect_ratio}")

    width, height, lay = frame.shape

    # fix width
    fixed_aspect = display_aspect_ratio / (width / height)
    width = int(width * fixed_aspect)
    # resize with fixed width (cv2)
    return cv2.resize(frame, (width, height))


def fix_frame(path, frame, check_palette=True, display_aspect_ratio=None):
    """
    Do all the needed fixes so the final frame looks really good.

    :param path: video path
    :param frame: cv2 Image array
    :param check_palette: check if the frame needs a palette
    :param display_aspect_ratio
    """
    logger.info(f"Fixing frame (check_palette: {check_palette})")

    resized = fix_dar(path, frame, display_aspect_ratio)
    # trim image if black borders are present. Convert to PIL first
    #    pil_image = cv2_to_pil(resized)
    #
    #    trim_image = trim(pil_image)
    #
    #    if not is_bw(cv2_to_pil(resized)):
    resized = cv2_trim(resized)

    # final_image = center_crop_image(trim_image)
    final_image = prettify_aspect(cv2_to_pil(resized))

    if check_palette:
        # return an extra bool if check_palette is True
        return (final_image, not is_bw(final_image))

    return final_image


def harmonic_wrap(text):
    """
    Harmonically wrap long text so it looks good on the frame.

    :param text
    """
    text_len = len(text)
    text_len_half = text_len / 2

    inc = 25
    while True:
        split_text = textwrap.wrap(text, width=inc)

        if abs(text_len - inc) < text_len_half and len(split_text) < 3:
            break

        if len(split_text) == 1 or inc > 50:
            break

        if len(split_text) != 2:
            inc += 3
            continue

        text1, text2 = split_text
        if abs(len(text1) - len(text2)) <= 5:
            logger.info(f"Optimal text wrap width found: {inc}")
            break

        inc += 3

    return "\n".join(split_text)


def prettify_quote(text):
    """
    Adjust line breaks to correctly draw a subtitle.

    :param text: text
    """
    lines = [" ".join(line.split()) for line in text.split("\n")]
    final_text = "\n".join(lines)

    if len(lines) == 2 and not any("-" in line for line in lines):
        if abs(len(lines[0]) - len(lines[1])) > 30:
            final_text = harmonic_wrap(final_text.replace("\n", " "))

    if (len(lines) == 1 and len(text) > 35) or len(lines) > 2:
        final_text = harmonic_wrap(final_text)

    # Don't use str.join() as it will remove line breaks
    final_text = re.sub(" +", " ", final_text)

    if len(re.findall("-", final_text)) == 1 and final_text.startswith("-"):
        final_text = final_text.replace("-", "").strip()

    if final_text.endswith(("?", "!", "-", ":", ".", ";", ",", '"')):
        return final_text

    return final_text + "."


def get_frame_from_movie_(path, second, microsecond=0):
    """
    Get an image array based on seconds and microseconds with cv2.
    Microseconds are only used for frames with quotes to improve scene syncing.

    :param path: video path
    :param second: second
    :param microsecond: microsecond
    """
    logger.info("Extracting frame")

    discriminator = f"{path}{second}{microsecond}"

    cached_img = get_cached_image(discriminator)
    if cached_img is not None:
        return cached_img

    capture = cv2.VideoCapture(path)

    fps = capture.get(cv2.CAP_PROP_FPS)

    extra_frames = int(fps * (microsecond * 0.000001)) * 2

    frame_start = int(fps * second) + extra_frames

    logger.info(f"Frame: {frame_start} (FPS: {fps}, extra frames: {extra_frames})")

    capture.set(1, frame_start)
    ret, frame = capture.read()

    cache_image(frame, discriminator)

    return frame


def get_frame_from_movie(path, second, microsecond=0):
    """
    Get an image array based on seconds and microseconds. Microseconds are
    only used for frames with quotes to improve scene syncing.

    :param path: video path
    :param second: second
    :param microsecond: microsecond
    """
    logger.info("Extracting frame")

    discriminator = f"{path}{second}{microsecond}"

    cached_img = get_cached_image(discriminator)
    if cached_img is not None:
        return cached_img

    frame = extract_frame_ffmpeg(path, f"{second}.{int(microsecond / 1000)}")
    cache_image(frame, discriminator)

    return frame


def extract_frame_ffmpeg(path, timestamp: str):
    """
    Get image array using ffmpeg. Useful when OpenCV fails.

    :param path: video path
    :param second: second
    """
    logger.info(f"Extracting {timestamp} timestamp with ffmpeg")
    tmp_image = os.path.join(gettempdir(), f"{timestamp}.png")

    command = [
        "ffmpeg",
        "-y",
        "-v",
        "quiet",
        "-stats",
        "-ss",
        timestamp,
        "-i",
        path,
        "-vf",
        "scale=iw*sar:ih",
        "-vframes",
        "1",
        "-q:v",
        "2",
        tmp_image,
    ]

    logger.info("Command: %s", command)
    subprocess.run(command, stdout=subprocess.PIPE)
    new_image = cv2.imread(tmp_image)

    try:
        os.remove(tmp_image)
    except OSError:
        pass

    return new_image


def draw_quote(pil_image, quote):
    """
    :param pil_image: PIL.Image object
    :param quote: quote
    :param sd_source: reduce stroke_width for low-res sources
    :raises exceptions.OffensiveWord
    """
    logger.info("Drawing subtitle")

    font = FONT
    if quote.startswith('"') and quote.endswith('"'):
        logger.info("Quoted string found")
        font = FONT_OBLIQUE

    #    check_offensive_content(quote)
    quote = prettify_quote(clean_sub(quote))

    draw = ImageDraw.Draw(pil_image)

    width, height = pil_image.size
    font_size = int((width * 0.022) + (height * 0.022))
    font = ImageFont.truetype(font, font_size)
    # 0.067
    off = width * 0.085
    txt_w, txt_h = draw.textsize(quote, font)

    stroke = int(width * 0.0025)

    draw.text(
        ((width - txt_w) / 2, height - txt_h - off),
        quote,
        "white",
        font=font,
        align="center",
        stroke_width=stroke,
        stroke_fill="black",
    )

    return pil_image


def get_final_frame(
    path,
    second=None,
    subtitle=None,
    multiple=False,
    ignore_quote=False,
    millisecond=0,
):
    """
    Get a frame from seconds or subtitles, all with a lot of post-processing
    so the final frame looks good. If multiple is True, palette checks will
    be ignored.

    :param path: video path
    :param second: second
    :param subtitle: subtitle dictionary from subs module
    :param multiple (bool)
    :param ignore_quote
    :param milliseconds
    :raises exceptions.OffensiveWord
    """
    if subtitle:
        cv2_obj = get_frame_from_movie(path, subtitle["start"], subtitle["start_m"])
        the_pil, palette_needed = fix_frame(path, cv2_obj, True)
        if not ignore_quote:
            the_pil = draw_quote(the_pil, subtitle["message"])
    else:
        cv2_obj = get_frame_from_movie(path, second, microsecond=millisecond * 1000)
        the_pil, palette_needed = fix_frame(path, cv2_obj, True)

    if multiple:
        return the_pil

    return get_palette(the_pil) if palette_needed else the_pil
