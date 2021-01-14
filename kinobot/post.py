#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import os
import sys
import time
from datetime import datetime
from functools import reduce
from random import choice
from textwrap import wrap

import click
import facepy
from discord_webhook import DiscordWebhook
from facepy import GraphAPI
from requests.exceptions import RequestException
import kinobot.exceptions as exceptions

from kinobot.db import (
    block_user,
    get_list_of_movie_dicts,
    get_list_of_episode_dicts,
    get_requests,
    insert_request_info_to_db,
    insert_episode_request_info_to_db,
    update_request_to_used,
    POSTERS_DIR,
)
from kinobot.discover import discover_movie
from kinobot.request import Request
from kinobot.utils import (
    check_image_list_integrity,
    get_collage,
    guess_nsfw_info,
    kino_log,
    is_episode,
)

from kinobot import (
    FACEBOOK,
    FACEBOOK_TV,
    FILM_COLLECTION,
    FRAMES_DIR,
    KINOLOG,
    KINOBOT_ID,
    REQUESTS_DB,
    DISCORD_WEBHOOK,
    DISCORD_WEBHOOK_TEST,
)

COMMANDS = ("!req", "!country", "!year", "!director")
RANGE_PRIOR = "00 03 09 12 15 18 21"
WEBSITE = "https://kino.caretas.club"
FACEBOOK_URL = "https://www.facebook.com/certifiedkino"
FACEBOOK_URL_TV = "https://www.facebook.com/kinobotv"
GITHUB_REPO = "https://github.com/vitiko98/kinobot"

MOVIES = get_list_of_movie_dicts()
EPISODES = get_list_of_episode_dicts()

FB = GraphAPI(FACEBOOK)
FB_TV = GraphAPI(FACEBOOK_TV)

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
        if any(guessed > 0.2 for guessed in nsfw_tuple):
            logger.info(f"Possible NSFW content from {image}")
            raise exceptions.NSFWContent


def get_description(item_dictionary, request_dictionary):
    """
    :param item_dictionary: movie/episode dictionary
    :param request_dictionary
    """
    if request_dictionary["is_episode"]:
        title = (
            f"{item_dictionary['title']} - Season {item_dictionary['season']}"
            f", Episode {item_dictionary['episode']}\nWriter: "
            f"{item_dictionary['writer']}\nCategory: {item_dictionary['category']}"
        )
    else:
        pretty_title = item_dictionary["title"]

        if (
            item_dictionary["title"].lower()
            != item_dictionary["original_title"].lower()
            and len(item_dictionary["original_title"]) < 45
        ):
            pretty_title = (
                f"{item_dictionary['original_title']} [{item_dictionary['title']}]"
            )

        title = (
            f"{pretty_title} ({item_dictionary['year']})\nDirector: "
            f"{item_dictionary['director']}\nCategory: {item_dictionary['category']}"
        )

    time_ = datetime.now().strftime("Finished at %H:%M GMT-4")
    description = (
        f"{title}\n\nRequested by {request_dictionary['user']} ({request_dictionary['type']} "
        f"{request_dictionary['comment']})\n\n{time_}\nThis bot is open source: {GITHUB_REPO}"
    )

    return description


def post_multiple(images, description, published=False, episode=False):
    """
    :param images: list of image paths
    :param description: description
    :param published
    :param episode
    """
    api_obj = FB_TV if episode else FB
    url = FACEBOOK_URL if episode else FACEBOOK_URL_TV
    logger.info("Posting multiple images")
    photo_ids = []
    for image in images:
        photo_ids.append(
            {
                "media_fbid": api_obj.post(
                    path="me/photos", source=open(image, "rb"), published=False
                )["id"]
            }
        )
    final = api_obj.post(
        path="me/feed",
        attached_media=json.dumps(photo_ids),
        message=description,
        published=published,
    )

    logger.info(f"Posted: {url}/posts/{final['id'].split('_')[-1]}")

    return final["id"]


def post_request(
    images,
    movie_info,
    request,
    published=False,
    episode=False,
):
    """
    :param images: list of image paths
    :param movie_info: movie dictionary
    :param request: request dictionary
    :param published
    :param episode
    """
    api_obj = FB_TV if episode else FB
    url = FACEBOOK_URL if episode else FACEBOOK_URL_TV
    description = get_description(movie_info, request)

    if not published:
        logger.info("Description:\n" + description + "\n")
        return

    if len(images) > 1:
        return post_multiple(images, description, published, episode)

    logger.info(f"Posting single image (episode: {episode})")

    post_id = api_obj.post(
        path="me/photos",
        source=open(images[0], "rb"),
        published=published,
        message=description,
    )

    logger.info(f"Posted: {url}/photos/{post_id['id']}")

    return post_id["id"]


def comment_post(post_id, published=False, episode=False):
    """
    :param post_id: Facebook post ID
    :param published
    :param episode
    """
    api_obj = FB_TV if episode else FB
    if episode:
        comment = (
            f"Explore the collection: {WEBSITE}/collection-tv\n\n"
            "If you request from this comment section, you'll "
            f"be registered as 'Unknown'. Please request on {FACEBOOK_URL}"
            " to avoid this limitation."
        )
    else:
        comment = (
            f"Explore the collection ({len(MOVIES)} Movies):\n{WEBSITE}\n"
            f"Are you a top user?\n{WEBSITE}/users/all\n"
            'Request examples:\n"!req Taxi Driver [you talking to me?]"\n"'
            '"!req Stalker [20:34] {TOTAL DURATION}"'
        )

    collage = os.path.join(POSTERS_DIR, choice(os.listdir(POSTERS_DIR)))
    logger.info(f"Found poster collage: {collage}")

    if not published:
        return

    comment_id = api_obj.post(
        path=f"{post_id}/comments",
        source=open(collage, "rb"),
        message=comment,
    )

    logger.info("Commented")


def notify(comment_id, reason=None, published=True, episode=False):
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
    if not published or episode:
        logger.info(f"{comment_id} notification message:\n{noti}\n")
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
    if nsfw:
        message = (
            f"Possible NSFW content found for {movie}. ID: "
            f"`{comment_dict.get('id')}`; user: `{comment_dict.get('user')}`"
        )
    else:
        message = f"Query finished for {movie} {comment_dict.get('content')}"

    webhook = DiscordWebhook(
        url=DISCORD_WEBHOOK_TEST if nsfw else DISCORD_WEBHOOK, content=message
    )

    for image in image_list:
        try:
            with open(image, "rb") as f:
                webhook.add_file(file=f.read(), filename=image.split("/")[-1])
        except:  # noqa
            pass
    try:
        webhook.execute()
    except Exception as error:
        logger.error(error, exc_info=True)


def get_reacts_count(post_id):
    """
    :param post_id: Facebook post/photo ID
    """
    if len(post_id.split("_")) == 1:
        post_id = f"{KINOBOT_ID}_{post_id}"

    reacts = FB.get(path=f"{post_id}/reactions")
    reacts_len = len(reacts.get("data", []))
    logger.info(f"Reacts from {post_id}: {reacts_len}")
    return reacts_len


def get_images(comment_dict, is_multiple, published=False):
    frames = []
    for frame in comment_dict["content"]:
        request = Request(
            comment_dict["movie"],
            frame,
            MOVIES,
            EPISODES,
            comment_dict,
            is_multiple,
            comment_dict["is_episode"],
        )
        if request.is_minute:
            request.handle_minute_request()
        else:
            try:
                request.handle_quote_request()
            except exceptions.ChainRequest:
                request.handle_chain_request()
                frames.append(request)
                break
        frames.append(request)

    final_image_list = [im.pill for im in frames]
    single_image_list = reduce(lambda x, y: x + y, final_image_list)

    check_image_list_integrity(single_image_list)

    if 1 < len(single_image_list) < 4:
        single_image_list = [get_collage(single_image_list, False)]

    saved_images = save_images(single_image_list, frames[0].movie, comment_dict)

    if not comment_dict["verified"] and published:
        try:
            check_nsfw(saved_images)
        except exceptions.NSFWContent:
            notify_discord(frames[0].movie, saved_images, comment_dict, True)
            raise

    notify_discord(frames[0].movie, saved_images, comment_dict)

    return saved_images, frames


def handle_request_item(request_dict, published):
    """
    :param request_list: request dictionarie
    :param published: directly publish to Facebook
    """
    block_user(request_dict["user"], check=True)
    request_command = request_dict["type"]
    request_dict["is_episode"] = is_episode(request_dict["movie"])

    if len(request_dict["content"]) > 20:
        raise exceptions.TooLongRequest

    logger.info(
        f"Request command: {request_command} {request_dict['comment']} "
        f"(Episode: {request_dict['is_episode']})"
    )

    if "req" not in request_command:
        if len(request_dict["content"]) != 1:
            raise exceptions.BadKeywords

        req_dict = discover_movie(
            request_dict["movie"],
            request_command.replace("!", ""),
            request_dict["content"][0],
        )
        request_dict["movie"] = f"{req_dict['title']} {req_dict['year']}"
        req_dict["content"] = [req_dict["quote"]]

    is_multiple = len(request_dict["content"]) > 1
    final_imgs, frames = get_images(request_dict, is_multiple, published)

    try:
        post_id = post_request(
            final_imgs,
            frames[0].movie,
            request_dict,
            published,
            request_dict["is_episode"],
        )
    except facepy.exceptions.OAuthError as error:
        message = f"Something is wrong with the Facebook token: {error}"
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_TEST, content=message)
        webhook.execute()
        sys.exit(message)

    try:
        comment_post(post_id, published, request_dict["is_episode"])
        notify(request_dict["id"], None, published, request_dict["is_episode"])
    except (facepy.exceptions.FacepyError, RequestException) as error:
        logger.error(error, exc_info=True)
    finally:
        if request_dict["is_episode"]:
            insert_episode_request_info_to_db(frames[0].movie, request_dict["user"])
        else:
            insert_request_info_to_db(frames[0].movie, request_dict["user"])

        update_request_to_used(request_dict["id"])
        logger.info("Request finished successfully")

        return post_id


def handle_request_list(request_list, published=True):
    """
    :param request_list: list of request dictionaries
    :param published: directly publish to Facebook
    """
    logger.info(f"Starting request handler (published: {published})")
    exception_count = 0
    for request_dict in request_list:
        try:
            return handle_request_item(request_dict, published)
        except exceptions.RestingMovie:
            # ignore recently requested movies
            continue
        except (FileNotFoundError, OSError, TimeoutError) as error:
            # to check missing or corrupted files
            exception_count += 1
            logger.error(error, exc_info=True)
            continue
        except (exceptions.BlockedUser, exceptions.NSFWContent):
            update_request_to_used(request_dict["id"])
        except Exception as error:
            logger.error(error, exc_info=True)
            exception_count += 1
            update_request_to_used(request_dict["id"])
            message = type(error).__name__
            if "offens" in message.lower():
                block_user(request_dict["user"])
            notify(request_dict["id"], message, published)
        if exception_count > 20:
            logger.warning("Exception limit exceeded")
            break


def post(filter_type="movies", test=False):
    " Find a valid request and post it to Facebook. "

    if test and not REQUESTS_DB.endswith(".save"):
        sys.exit("Kinobot can't run test mode at this time")

    check_directory()

    hour = datetime.now().strftime("%H")
    logger.info(f"Test mode: {test} [hour {hour}]")

    priority_list = None
    if hour in RANGE_PRIOR:
        priority_list = get_requests(filter_type, True)

    request_list = get_requests(filter_type)

    logger.info(f"Requests found in normal list: {len(request_list)}")

    if priority_list:
        logger.info(f"Requests found in priority list: {len(priority_list)}")
        post_id = handle_request_list(priority_list, published=not test)
        if not post_id:
            logger.info("Falling back to normal list")
            post_id = handle_request_list(request_list, published=not test)
    else:
        post_id = handle_request_list(request_list, published=not test)

    logger.info("FINISHED\n" + "#" * 70)

    return post_id


@click.command("post")
def publish():
    " Find a valid request and post it to Facebook. "
    kino_log(KINOLOG)
    post("episodes")
    post()


@click.command("test")
def testing():
    " Find a valid request for tests. "
    kino_log(KINOLOG + ".test")
    post(test=True)
    post("episodes", test=True)
