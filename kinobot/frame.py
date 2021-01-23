#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import os
import subprocess
import textwrap

import cv2
import timeout_decorator
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat
from pymediainfo import MediaInfo

from kinobot.exceptions import InconsistentImageSizes
from kinobot.palette import get_palette
from kinobot.utils import clean_sub, check_offensive_content
from kinobot import FONTS, FRAMES_DIR

FONT = os.path.join(FONTS, "NS_Medium.otf")
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
    off = int(height * 0.025)

    return pil_image.crop((0, off, width, height - off))


def cv2_to_pil(cv2_array):
    """
    Convert an array to a PIL.Image object.

    :param cv2_array: image array from cv2
    """
    image = cv2.cvtColor(cv2_array, cv2.COLOR_BGR2RGB)
    return Image.fromarray(image)


def image_magick_trim(pil_image):
    """
    Trim black borders from an image with ImageMagick's algorithm. This method
    seems to be more effective than PIL's ImageChops from pil_trim.

    :param pil_image: PIL.Image object
    """
    tmp_image = os.path.join(FRAMES_DIR, ".tmp.jpg")
    pil_image.save(tmp_image)
    command = [
        "convert",
        tmp_image,
        "-bordercolor",
        "black",
        "-trim",
        tmp_image,
    ]
    subprocess.run(command, stdout=subprocess.PIPE, timeout=30)
    final_image = Image.open(tmp_image)
    os.remove(tmp_image)
    return final_image


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


def center_crop_image(pil_image, square=False):
    """
    Crop a image if is too wide as it doesn't look good on Facebook.
    Very anti-kino, isn't it? But let's don't kill the reach.

    :param pil_image: PIL.Image object
    :param square: trim extra borders from square frames
    """
    width, height = pil_image.size
    quotient = width / height

    if quotient <= 2.25 and not square:
        return pil_image

    logger.info(f"Cropping too wide image ({quotient})")
    new_width = width * (0.8 if not square else 0.9)
    left = (width - new_width) / 2
    right = (width + new_width) / 2
    bottom = height

    try:
        return pil_image.crop((int(left), 0, int(right), bottom))
    except Exception as error:
        logger.error(error, exc_info=True)
        return pil_image


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

    if abs(og_quotient - new_quotient) > 60:
        raise InconsistentImageSizes(f"{og_quotient}/{new_quotient}")

    if abs(og_w - new_w) > 5 or abs(og_h - new_h) > 5:
        logger.info("Fixing trim")
        return center_crop_image(fix_web_source(trim_), square=True)

    return trim_


def fix_frame(path, frame, check_palette=True, display_aspect_ratio=None):
    """
    Do all the needed fixes so the final frame looks really good.

    :param path: video path
    :param frame: cv2 Image array
    :param check_palette: check if the frame needs a palette
    :param display_aspect_ratio
    """
    logger.info(f"Fixing frame (check_palette: {check_palette})")

    if not display_aspect_ratio:
        display_aspect_ratio = get_dar(path)

    logger.info(f"Found DAR: {display_aspect_ratio}")
    # fix width
    width, height, lay = frame.shape
    logger.info(f"Original dimensions: {width}*{height}")
    fixed_aspect = display_aspect_ratio / (width / height)
    width = int(width * fixed_aspect)
    # resize with fixed width (cv2)
    logger.info(f"Fixed dimensions: {width}*{height}")
    resized = cv2.resize(frame, (width, height))
    # trim image if black borders are present. Convert to PIL first
    pil_image = cv2_to_pil(resized)

    trim_image = trim(pil_image)

    final_image = center_crop_image(trim_image)

    if check_palette:
        # return an extra bool if check_palette is True
        return (final_image, not is_bw(final_image))

    return final_image


def prettify_quote(text):
    """
    Adjust line breaks to correctly draw a subtitle.

    :param text: text
    """
    lines = [" ".join(line.split()) for line in text.split("\n")]

    if len(lines) == 1 and len(text) > 45:
        return textwrap.fill(text, width=45)

    if len(lines) > 2:
        return textwrap.fill(" ".join(lines), width=45)

    return "\n".join(lines)


def get_frame_from_movie(path, second, microsecond=0):
    """
    Get an image array based on seconds and microseconds. Microseconds are
    only used for frames with quotes to improve scene syncing.

    :param path: video path
    :param second: second
    :param microsecond: microsecond
    """
    logger.info("Extracting frame")
    capture = cv2.VideoCapture(path)

    fps = capture.get(cv2.CAP_PROP_FPS)

    extra_frames = int(fps * (microsecond * 0.000001)) * 2

    frame_start = int(fps * second) + extra_frames

    logger.info(f"Frame: {frame_start} (FPS: {fps}, extra frames: {extra_frames})")

    capture.set(1, frame_start)
    ret, frame = capture.read()

    return frame


def extract_frame_ffmpeg(path, second):
    """
    Get image array using ffmpeg. Useful when OpenCV fails.

    :param path: video path
    :param second: second
    """
    logger.info("Extracting frame with ffmpeg")
    tmp_image = "/tmp/tmp_pil.png"
    command = [
        "ffmpeg",
        "-ss",
        str(second),
        "-copyts",
        "-i",
        path,
        "-vf",
        "scale=iw*sar:ih",
        "-vframes",
        "1",
        tmp_image,
    ]
    subprocess.run(command, stdout=subprocess.PIPE)
    new_image = cv2.imread(tmp_image)
    os.remove(tmp_image)
    return new_image


def draw_quote(pil_image, quote):
    """
    :param pil_image: PIL.Image object
    :param quote: quote
    :param sd_source: reduce stroke_width for low-res sources
    :raises exceptions.OffensiveWord
    """
    logger.info("Drawing subtitle")

    check_offensive_content(quote)
    quote = prettify_quote(clean_sub(quote))

    draw = ImageDraw.Draw(pil_image)

    width, height = pil_image.size
    font_size = int((width * 0.019) + (height * 0.019))
    font = ImageFont.truetype(FONT, font_size)
    # 0.067
    off = width * 0.08
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


@timeout_decorator.timeout(15, use_signals=False)
def get_final_frame(
    path,
    second=None,
    subtitle=None,
    multiple=False,
    display_aspect_ratio=None,
    ignore_quote=False,
):
    """
    Get a frame from seconds or subtitles, all with a lot of post-processing
    so the final frame looks good. If multiple is True, palette checks will
    be ignored.

    :param path: video path
    :param second: second
    :param subtitle: subtitle dictionary from subs module
    :param multiple (bool)
    :param display_aspect_ratio
    :param ignore_quote
    :raises exceptions.OffensiveWord
    :raises timeout_decorator.TimeoutError
    """
    if subtitle:
        cv2_obj = get_frame_from_movie(path, subtitle["start"], subtitle["start_m"])
        the_pil, palette_needed = fix_frame(path, cv2_obj, True, display_aspect_ratio)
        if not ignore_quote:
            the_pil = draw_quote(the_pil, subtitle["message"])
    else:
        cv2_obj = get_frame_from_movie(path, int(second), microsecond=0)
        the_pil, palette_needed = fix_frame(path, cv2_obj, True, display_aspect_ratio)

    if multiple:
        return the_pil

    return get_palette(the_pil) if palette_needed else the_pil
