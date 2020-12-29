#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from functools import reduce
from textwrap import wrap

import click
import facepy
from discord_webhook import DiscordWebhook
from facepy import GraphAPI

import kinobot.exceptions as exceptions

from kinobot.db import (
    block_user,
    get_list_of_movie_dicts,
    get_requests,
    insert_request_info_to_db,
    update_request_to_used,
)
from kinobot.discover import discover_movie
from kinobot.request import Request
from kinobot.utils import (
    check_image_list_integrity,
    get_collage,
    get_poster_collage,
    guess_nsfw_info,
)

from kinobot import (
    FACEBOOK,
    FILM_COLLECTION,
    FRAMES_DIR,
    KINOLOG,
    REQUESTS_DB,
    DISCORD_WEBHOOK,
)

COMMANDS = ("!req", "!country", "!year", "!director")
WEBSITE = "https://kino.caretas.club"
FACEBOOK_URL = "https://www.facebook.com/certifiedkino"
GITHUB_REPO = "https://github.com/vitiko98/kinobot"
MOVIES = get_list_of_movie_dicts()
TIME = datetime.now().strftime("Automatically executed at %H:%M GMT-4")
FB = GraphAPI(FACEBOOK)

logger = logging.getLogger(__name__)


def check_directory():
    if not os.path.isdir(FILM_COLLECTION):
        sys.exit(f"Collection not mounted: {FILM_COLLECTION}")


def save_images(pil_list, movie_dict, comment_dict):
    """
    :param pil_list: list PIL.Image objects
    :param movie_dict: movie dictionary
    :param movie_dict: comment_dict dictionary
    """
    directory = os.path.join(FRAMES_DIR, str(time.time()))
    os.makedirs(directory, exist_ok=True)

    text = (
        f"{movie_dict.get('title')} ({movie_dict.get('year')}) *** "
        f"{comment_dict.get('type')} {comment_dict.get('content')}"
    )
    with open(os.path.join(directory, "info.txt"), "w") as text_info:
        text_info.write("\n".join(wrap(text, 70)))

    names = [os.path.join(directory, f"{n[0]:02}.jpg") for n in enumerate(pil_list)]

    for image, name in zip(pil_list, names):
        image.save(name)
        logger.info(f"Saved: {name}")

    return names


def check_nsfw(image_list):
    logger.info("Checking for NSFW content")
    for image in image_list:
        nsfw_tuple = guess_nsfw_info(image)
        logger.info(nsfw_tuple)
        if any(guessed > 0.3 for guessed in nsfw_tuple):
            logger.info(f"Possible NSFW content from {image}")
            raise exceptions.NSFWContent


def post_multiple(images, description, published=False):
    """
    :param images: list of image paths
    :param description: description
    :param published
    """
    logger.info("Post multiple images")
    photo_ids = []
    for image in images:
        photo_ids.append(
            {
                "media_fbid": FB.post(
                    path="me/photos", source=open(image, "rb"), published=False
                )["id"]
            }
        )
    final = FB.post(
        path="me/feed",
        attached_media=json.dumps(photo_ids),
        message=description,
        published=published,
    )
    logger.info(f"Posted: {FACEBOOK_URL}/posts/{final['id'].split('_')[-1]}")
    return final["id"]


def post_request(
    images, movie_info, request, request_command, is_multiple=True, published=False
):
    """
    :param images: list of image paths
    :param movie_info: movie dictionary
    :param request: request dictionary
    :param request_command: request command string
    :param is_multiple
    :param published
    """
    if not published:
        return

    pretty_title = movie_info["title"]

    if (
        movie_info["title"].lower() != movie_info["original_title"].lower()
        and len(movie_info["original_title"]) < 45
    ):
        pretty_title = f"{movie_info['original_title']} [{movie_info['title']}]"

    title = (
        f"{pretty_title} ({movie_info['year']})\nDirector: "
        f"{movie_info['director']}\nCategory: {movie_info['category']}"
    )

    description = (
        f"{title}\n\nRequested by {request['user']} ({request_command} "
        f"{request['comment']})\n\n{TIME}\nThis bot is open source: {GITHUB_REPO}"
    )

    if len(images) > 1:
        return post_multiple(images, description, published)

    logger.info("Posting single image")

    post_id = FB.post(
        path="me/photos",
        source=open(images[0], "rb"),
        published=published,
        message=description,
    )

    logger.info(f"Posted: {FACEBOOK_URL}/photos/{post_id['id']}")

    return post_id["id"]


def comment_post(post_id, published=False):
    """
    :param post_id: Facebook post ID
    :param published
    """
    comment = (
        f"Explore the collection ({len(MOVIES)} Movies):\n{WEBSITE}\n"
        f"Are you a top user?\n{WEBSITE}/users/all\n"
        'Request examples:\n"!req Taxi Driver [you talking to me?]"\n"'
        '!req Stalker [20:34]"\n"!req A Man Escaped [21:03] [23:02]"'
    )
    if not published:
        logger.info(f"{post_id} comment:\n{comment}")
        return

    poster_collage = get_poster_collage(MOVIES)
    if not poster_collage:
        return

    poster_collage.save("/tmp/tmp_collage.jpg")

    FB.post(
        path=post_id + "/comments",
        source=open("/tmp/tmp_collage.jpg", "rb"),
        message=comment,
    )
    logger.info("Commented")


def notify(comment_id, reason=None, published=True):
    """
    :param comment_id: Facebook comment ID
    :param reason: exception string
    """
    if not reason:
        noti = (
            "202: Your request was successfully executed.\n"
            f"Are you in the list of top users? {WEBSITE}/users/all\n"
            f"Check the complete list of movies: {WEBSITE}"
        )
    else:
        if "offen" in reason.lower() or "discord" in reason:
            noti = (
                "You are a really good comedian, ain't ye? You are blocked. "
                "Don't reply to this comment; it was automatically executed."
            )
        else:
            noti = (
                f"Kinobot returned an error: {reason}. Please, don't forget "
                "to check the list of available films and instructions"
                f" before making a request: {WEBSITE}"
            )
    if not published:
        logger.info(f"{comment_id} notification message:\n{noti}")
        return
    try:
        FB.post(path=comment_id + "/comments", message=noti)
    except facepy.exceptions.FacebookError:
        logger.info("The comment was deleted")


def notify_discord(movie_dict, image_list, comment_dict=None, nsfw=False):
    """
    :param movie_dict: movie dictionary
    :param image_list: list of jpg image paths
    :param comment_dict: comment dictionary
    :param nsfw: notify NSFW
    """
    logger.info(f"Sending notification to Botmin (nsfw: {nsfw})")

    movie = f"{movie_dict.get('title')} ({movie_dict.get('year')})"
    if nsfw and comment_dict:
        message = (
            f"Possible NSFW content found for {movie}. ID: "
            f"`{comment_dict.get('id')}`; user: `{comment_dict.get('user')}`"
        )
    else:
        message = f"Query finished for {movie}"

    webhook = DiscordWebhook(url=DISCORD_WEBHOOK, content=message)

    for image in image_list:
        try:
            with open(image, "rb") as f:
                webhook.add_file(file=f.read(), filename=image.split("/")[-1])
        except:  # noqa
            pass

    webhook.execute()


def get_images(comment_dict, is_multiple):
    frames = []
    for frame in comment_dict["content"]:
        request = Request(comment_dict["movie"], frame, MOVIES, is_multiple)
        if request.is_minute:
            request.handle_minute_request()
        else:
            request.handle_quote_request()
        frames.append(request)

    final_image_list = [im.pill for im in frames]
    single_image_list = reduce(lambda x, y: x + y, final_image_list)

    check_image_list_integrity(single_image_list)

    if len(single_image_list) < 4:
        single_image_list = [get_collage(single_image_list, False)]

    saved_images = save_images(single_image_list, frames[0].movie, comment_dict)

    if not comment_dict["verified"]:
        try:
            check_nsfw(saved_images)
        except exceptions.NSFWContent:
            notify_discord(frames[0].movie, saved_images, comment_dict, True)
            raise

    notify_discord(frames[0].movie, saved_images)

    return saved_images, frames


def handle_requests(published=True):
    logger.info(f"Starting request handler (published: {published})")
    requests_ = get_requests()
    random.shuffle(requests_)

    exception_count = 0
    for m in requests_:
        try:
            block_user(m["user"], check=True)
            request_command = m["type"]

            if len(m["content"]) > 20:
                raise exceptions.TooLongRequest

            logger.info(f"Request command: {request_command} {m['comment']}")

            if "req" not in request_command:
                if len(m["content"]) != 1:
                    raise exceptions.BadKeywords

                req_dict = discover_movie(
                    m["movie"], request_command.replace("!", ""), m["content"][0]
                )
                m["movie"] = req_dict["title"] + " " + str(req_dict["year"])
                m["content"] = [req_dict["quote"]]

            is_multiple = len(m["content"]) > 1
            final_imgs, frames = get_images(m, is_multiple)
            try:
                post_id = post_request(
                    final_imgs,
                    frames[0].movie,
                    m,
                    request_command,
                    is_multiple,
                    published,
                )
            except facepy.exceptions.OAuthError:
                sys.exit("Something is wrong with the account. Exiting now")

            comment_post(post_id, published)
            notify(m["id"], None, published)

            insert_request_info_to_db(frames[0].movie, m["user"])
            update_request_to_used(m["id"])
            logger.info("Request finished successfully")
            break
        except exceptions.RestingMovie:
            # ignore recently requested movies
            continue
        except (FileNotFoundError, OSError) as error:
            # to check missing or corrupted files
            exception_count += 1
            logger.error(error, exc_info=True)
            continue
        except (exceptions.BlockedUser, exceptions.NSFWContent):
            update_request_to_used(m["id"])
        except Exception as error:
            logger.error(error, exc_info=True)
            exception_count += 1
            update_request_to_used(m["id"])
            message = type(error).__name__
            if "offens" in message.lower():
                block_user(m["user"])
            notify(m["id"], message, published)
        if exception_count > 20:
            logger.warning("Exception limit exceeded")
            break


def post(test=False):
    " Find a valid request and post it to Facebook. "

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(module)s.%(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(KINOLOG), logging.StreamHandler()],
    )
    if test and not REQUESTS_DB.endswith(".save"):
        sys.exit("Kinobot can't run test mode at this time")

    logger.info(f"Test mode: {test}")
    check_directory()
    handle_requests(published=not test)
    logger.info("FINISHED\n" + "#" * 70)


@click.command("post")
def publish():
    " Find a valid request and post it to Facebook. "
    post()


@click.command("test")
def testing():
    " Find a valid request for tests. "
    post(test=True)
