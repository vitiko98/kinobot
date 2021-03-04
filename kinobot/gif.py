#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import logging
import os

import cv2

from kinobot.exceptions import InvalidRequest
from kinobot.frame import cv2_to_pil, draw_quote, fix_dar, get_dar, prettify_aspect
from kinobot.utils import (
    convert_request_content,
    get_subtitle,
    get_cached_image,
    cache_image,
)
from kinobot.request import (
    find_quote,
    guess_subtitle_chain,
    search_movie,
    search_episode,
)

from kinobot import FRAMES_DIR

logger = logging.getLogger(__name__)


def sanity_checks(subtitle_list=[], range_=None):
    if len(subtitle_list) > 4:
        raise InvalidRequest(
            f"Expected less than 5 quotes, found {len(subtitle_list)}."
        )

    if range_:
        req_range = abs(range_[0] - range_[1])
        if req_range > 7:
            raise InvalidRequest(
                f"Expected less than 8 seconds of range, found {req_range}."
            )


def scale_to_gif(frame):
    w, h = frame.shape[1], frame.shape[0]
    inc = 0.5
    while True:
        if w * inc < 650:
            break
        inc -= 0.1

    return cv2.resize(frame, (int(w * inc), int(h * inc)))


def start_end_gif(fps, sub_dict=None, range_=None):
    if sub_dict:
        extra_frames_start = int(fps * (sub_dict["start_m"] * 0.000001))
        extra_frames_end = int(fps * (sub_dict["end_m"] * 0.000001))
        frame_start = int(fps * sub_dict["start"]) + extra_frames_start
        frame_end = int(fps * sub_dict["end"]) + extra_frames_end
        return (frame_start, frame_end)

    return (int(fps * range_[0]), int(fps * range_[1]))


def get_image_list_from_range(path, range_=(0, 7), dar=None):
    """
    :param path: video path
    :param subs: range of seconds
    :param dar: display aspect ratio from video
    """
    sanity_checks(range_=range_)

    logger.info("About to extract GIF for range %s", range_)

    capture = cv2.VideoCapture(path)
    if not dar:
        dar = get_dar(path)

    fps = capture.get(cv2.CAP_PROP_FPS)
    start, end = start_end_gif(fps, range_=range_)

    logger.info(f"Start: {start} - end: {end}; diff: {start - end}")
    for i in range(start, end, 4):
        discriminator = f"{path}{i}_gif"
        cached_img = get_cached_image(discriminator)

        if cached_img is not None:
            yield prettify_aspect(cv2_to_pil(cached_img))
        else:
            capture.set(1, i)

            frame_ = scale_to_gif(fix_dar(path, capture.read()[1], dar))

            cache_image(frame_, discriminator)

            yield prettify_aspect(cv2_to_pil(frame_))


def get_image_list_from_subtitles(path, subs=[], dar=None):
    """
    :param path: video path
    :param subs: list of subtitle dictionaries
    :param dar: display aspect ratio from video
    """
    sanity_checks(subs)

    logger.info(f"Subtitles found: {len(subs)}")

    capture = cv2.VideoCapture(path)
    if not dar:
        dar = get_dar(path)

    fps = capture.get(cv2.CAP_PROP_FPS)
    for subtitle in subs:
        start, end = start_end_gif(fps, sub_dict=subtitle)
        end += 10
        end = end if abs(start - end) < 100 else (start + 100)
        logger.info(f"Start: {start} - end: {end}; diff: {start - end}")
        for i in range(start, end, 4):
            capture.set(1, i)
            pil = scale_to_gif(cv2_to_pil(fix_dar(path, capture.read()[1], dar)))
            yield draw_quote(prettify_aspect(pil), subtitle["message"])


def image_list_to_gif(images, filename="sample.gif"):
    """
    :param images: list of PIL.Image objects
    :param filename: output filename
    """
    logger.info(f"Saving GIF ({len(images)} images)")

    images[0].save(filename, format="GIF", append_images=images[1:], save_all=True)

    logger.info(f"Saved: {filename}")


def get_range(content):
    """
    :param content: string from request square bracket
    """
    seconds = [convert_request_content(second.strip()) for second in content.split("-")]

    if any(isinstance(second, str) for second in seconds):
        logger.info("String found. Quote request")
        return content

    if len(seconds) != 2:
        raise InvalidRequest(f"Expected 2 timestamps, found {len(seconds)}.")

    logger.info("Good gif timestamp request")
    return tuple(seconds)


def get_quote_list(subtitle_list, dictionary):
    """
    :param subtitle_list: list of srt.Subtitle objects
    :param dictionary: request dictionary
    """
    chain = guess_subtitle_chain(subtitle_list, dictionary)
    if not chain:
        chain = []
        for quote in dictionary["content"]:
            chain.append(find_quote(subtitle_list, quote))

    return chain


def handle_gif_request(dictionary, movie_list):
    """
    Handle a GIF request. Return movie dictionary and GIF file (inside a list
    to avoid problems with the API).

    :param dictionary: request dictionary
    :param movie_list: list of movie dictionaries
    """
    possible_range = get_range(dictionary["content"][0])

    search_handler = search_episode if dictionary["is_episode"] else search_movie

    movie = search_handler(movie_list, dictionary["movie"], raise_resting=False)

    subtitle_list = get_subtitle(movie)

    if isinstance(possible_range, tuple):
        image_list = list(get_image_list_from_range(movie["path"], possible_range))
    else:
        sub_list = get_quote_list(subtitle_list, dictionary)
        image_list = list(get_image_list_from_subtitles(movie["path"], sub_list))

    filename = os.path.join(FRAMES_DIR, f"{dictionary['id']}.gif")
    image_list_to_gif(image_list, filename)

    return movie, [filename]
