#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import os
import re
import subprocess

import cv2
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat
from pymediainfo import MediaInfo

import kinobot.exceptions as exceptions
from kinobot.config import FONTS
from kinobot.palette import get_palette

FONT = os.path.join(FONTS, "helvetica.ttf")

logger = logging.getLogger(__name__)


def is_bw(pil_image):
    """
    Guess if an image is B/W.

    :param pil_image: PIL.Image object
    """
    hsv = ImageStat.Stat(pil_image.convert("HSV"))
    return hsv.mean[1] < 35


def trim(pil_image):
    """
    Remove black borders from WEB sources if present. Ignore B/W movies
    and mostly black frames as they might fail.

    :param pil_image: PIL.Image Object
    """
    if is_bw(pil_image):
        return pil_image

    bg = Image.new(pil_image.mode, pil_image.size, pil_image.getpixel((0, 0)))
    diff = ImageChops.difference(pil_image, bg)
    diff = ImageChops.add(diff, diff)
    bbox = diff.getbbox()
    if bbox:
        return pil_image.crop(bbox)


def cv2_to_pil(cv2_array):
    """
    Convert an array to a PIL.Image object.

    :param cv2_array: image array from cv2
    """
    image = cv2.cvtColor(cv2_array, cv2.COLOR_BGR2RGB)
    return Image.fromarray(image)


def get_dar(path):
    """
    Get Display Aspect Ratio from ffprobe (Faster than MediaInfo but
    not reliable).

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
    result = subprocess.run(command, stdout=subprocess.PIPE)
    return json.loads(result.stdout)["streams"][0]["display_aspect_ratio"].split(":")


def center_crop_image(pil_image):
    """
    Crop a image if is too wide as it doesn't look good on Facebook.
    Very anti-kino, isn't it? But let's don't kill the reach.

    :param pil_image: PIL.Image object
    """
    width, height = pil_image.size
    quotient = width / height

    if quotient <= 2.25:
        return pil_image

    logger.info(f"Cropping too wide image ({quotient})")
    new_width = width * (0.75 if quotient <= 2.4 else 0.7)
    left = (width - new_width) / 2
    right = (width + new_width) / 2
    bottom = height

    try:
        return pil_image.crop((int(left), 0, int(right), bottom))
    except Exception as error:
        logger.error(error, exc_info=True)
        return pil_image


def fix_frame(path, frame, check_palette=True):
    """
    Do all the needed fixes so the final frame looks really good.

    :param path: video path
    :param frame: cv2 Image array
    :param check_palette: check if the frame needs a palette
    """

    logger.info("Checking DAR")
    try:
        logger.info("Using ffprobe")
        d_width, d_height = get_dar(path)
        display_aspect_ratio = float(d_width) / float(d_height)
    except:  # noqa
        logger.info("Using mediainfo. This will take a while")
        media_info = MediaInfo.parse(path, output="JSON")
        display_aspect_ratio = float(
            json.loads(media_info)["media"]["track"][1]["DisplayAspectRatio"]
        )
    logger.info(f"Extracted display aspect ratio: {display_aspect_ratio}")

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
        return (final_image, is_bw(final_image))

    return final_image


def clean_sub(text):
    """
    Remove unwanted characters from a subtitle string.

    :param text: text
    """
    cleaner = re.compile(r"<.*?>|🎶|♪")
    return re.sub(cleaner, "", text)


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
    logger.info(f"FPS: {fps}")

    extra_frames = int(25 * (microsecond * 0.000001)) if microsecond else 0
    logger.info(f"Calculated extra frames: {extra_frames}")

    frame_start = int(fps * second) + extra_frames

    capture.set(1, frame_start)
    ret, frame = capture.read()
    return frame


def check_offensive_content(text):
    """
    :param text: text
    :raises exceptions.OffensiveWord
    """
    with open(os.environ.get("OFFENSIVE_WORDS")) as words:
        if any(i in text.lower() for i in json.load(words)):
            raise exceptions.OffensiveWord


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
    :raises exceptions.OffensiveWord
    """
    logger.info("Drawing subtitle")

    check_offensive_content(quote)
    quote = clean_sub(quote)

    draw = ImageDraw.Draw(pil_image)
    width, height = pil_image.size
    font = ImageFont.truetype(FONT, int(height * 0.055))
    off = width * 0.067
    txt_w, txt_h = draw.textsize(quote, font)

    draw.text(
        ((width - txt_w) / 2, height - txt_h - off),
        quote,
        "white",
        font=font,
        align="center",
        stroke_width=4,
        stroke_fill="black",
    )

    return pil_image


def get_final_frame(path, second=None, subtitle=None, multiple=False):
    """
    Get a frame from seconds or subtitles, all with a lot of post-processing
    so the final frame looks good. If multiple is True, palette checks will
    be ignored.

    :param path: video path
    :param second: second
    :param subtitle: subtitle dictionary from subs module
    :param multiple (bool)
    :raises exceptions.OffensiveWord
    """
    if subtitle:
        cv2_obj = get_frame_from_movie(path, subtitle["start"], subtitle["start_m"])
        new_pil, palette_needed = fix_frame(path, cv2_obj)
        the_pil = draw_quote(new_pil, subtitle["message"])
    else:
        cv2_obj = get_frame_from_movie(path, int(second), microsecond=0)
        the_pil, palette_needed = fix_frame(path, cv2_obj)

    if multiple:
        return the_pil

    return get_palette(the_pil) if palette_needed else the_pil
