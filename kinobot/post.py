#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import os
import sys
import traceback
from datetime import datetime
from random import choice

import click
import facepy
import timeout_decorator
from discord_webhook import DiscordWebhook, DiscordEmbed
from facepy import GraphAPI
from requests.exceptions import RequestException

import kinobot.exceptions as exceptions

from kinobot.api import handle_request
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
from kinobot.utils import check_directory, check_nsfw, kino_log

from kinobot import (
    FACEBOOK,
    FACEBOOK_TV,
    KINOLOG,
    KINOBOT_ID,
    REQUESTS_DB,
    DISCORD_WEBHOOK,
    DISCORD_WEBHOOK_TEST,
    DISCORD_TRACEBACK,
)

PATREON = "https://patreon.com/kinobot"
RANGE_PRIOR = "00 03 09 11 12 15 18 21 23"
WEBSITE = "https://kino.caretas.club"
FACEBOOK_URL = "https://www.facebook.com/certifiedkino"
FACEBOOK_URL_TV = "https://www.facebook.com/kinobotv"
GITHUB_REPO = "https://github.com/vitiko98/kinobot"

FB = GraphAPI(FACEBOOK)
FB_TV = GraphAPI(FACEBOOK_TV)

logger = logging.getLogger(__name__)


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
    description,
    request,
    published=False,
):
    """
    :param images: list of image paths
    :param description: post description
    :param request: request dictionary
    :param published
    """
    api_obj = FB_TV if request["is_episode"] else FB
    url = FACEBOOK_URL if request["is_episode"] else FACEBOOK_URL_TV

    if not published:
        logger.info("Description:\n" + description + "\n")
        return

    if len(images) > 1:
        return post_multiple(images, description, published, request["is_episode"])

    logger.info(f"Posting single image (episode: {request['is_episode']})")

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
        episodes_len = len(get_list_of_episode_dicts())
        comment = (
            f"Become a patron and get access to on-demand requests: {PATREON}\n"
            f"Explore the collection ({episodes_len} episodes): "
            f"{WEBSITE}/collection-tv"
        )

    else:
        movies_len = len(get_list_of_movie_dicts())
        comment = (
            f"Become a patron and get access to on-demand requests: {PATREON}\n"
            f"Explore the collection ({movies_len} movies):\n{WEBSITE}\n"
            f"Completely open-source:\n{GITHUB_REPO}\n\n"
            "If you donated before Feb 3, you'll get an email with an invitation"
            " for on-demand requests in the next days."
        )

    collage = os.path.join(POSTERS_DIR, choice(os.listdir(POSTERS_DIR)))
    logger.info(f"Found poster collage: {collage}")

    if not published:
        return

    api_obj.post(
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


def notify_discord(image_list, comment_dict=None, nsfw=False):
    """
    :param image_list: list of jpg image paths
    :param comment_dict: comment dictionary
    :param nsfw: notify NSFW
    """
    logger.info(f"Sending notification to Botmin (nsfw: {nsfw})")

    if nsfw:
        message = (
            f"Possible NSFW content found for {comment_dict.get('comment')}. ID: "
            f"{comment_dict.get('id')}; user: {comment_dict.get('user')};"
        )
    else:
        message = f"Query finished for {comment_dict.get('comment')}"

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


def send_traceback_webhook(trace, request_dict, published):
    """
    :param trace: traceback string
    :param request: request dictionary
    :param published: send webhook
    """
    if not published:
        return

    webhook = DiscordWebhook(url=DISCORD_TRACEBACK)

    embed = DiscordEmbed(title=request_dict["comment"][:200], description=trace[:1000])
    embed.set_author(name=request_dict["user"])
    embed.add_embed_field(name="ID", value=request_dict["id"])

    webhook.add_embed(embed)

    webhook.execute()


def send_post_webhook(request_dict, published=False):
    """
    :param frames: finished request dictionary
    :param published: published
    """
    if not request_dict["final_request_dict"]["verified"] and published:
        logger.info("Checking images for NSFW content")
        try:
            check_nsfw(request_dict["images"])
        except exceptions.NSFWContent:
            notify_discord(
                request_dict["images"],
                request_dict["final_request_dict"],
                True,
            )
            raise
    logger.info("Non-published post")
    notify_discord(request_dict["images"], request_dict["final_request_dict"])


@timeout_decorator.timeout(120, use_signals=False)
def finish_request(request_dict, published):
    """
    :param request_list: request dictionaries
    :param published: directly publish to Facebook
    """
    result_dict = handle_request(request_dict)
    new_request = result_dict["final_request_dict"]
    send_post_webhook(result_dict, published)
    try:
        post_id = post_request(
            result_dict["images"],
            result_dict["description"],
            new_request,
            published,
        )
    except facepy.exceptions.OAuthError:
        sys.exit(
            send_traceback_webhook(traceback.format_exc(), request_dict, published)
        )

    try:
        comment_post(post_id, published, new_request["is_episode"])
        notify(request_dict["id"], None, published, new_request["is_episode"])

        if new_request["is_episode"]:
            insert_episode_request_info_to_db(
                result_dict["movie_dict"], new_request["user"]
            )
        else:
            insert_request_info_to_db(result_dict["movie_dict"], new_request["user"])

        update_request_to_used(new_request["id"])
        logger.info("Request finished successfully")

    except (facepy.exceptions.FacepyError, RequestException) as error:
        logger.error(error, exc_info=True)

    finally:
        return True


def handle_request_list(request_list, published=True):
    """
    :param request_list: list of request dictionaries
    :param published: directly publish to Facebook
    """
    logger.info(f"Starting request handler (published: {published})")
    exception_count = 0
    for request_dict in request_list:
        try:
            return finish_request(request_dict, published)
        except exceptions.RestingMovie:
            # ignore recently requested movies
            continue
        except (FileNotFoundError, OSError, timeout_decorator.TimeoutError) as error:
            # to check missing or corrupted files
            exception_count += 1
            logger.error(error, exc_info=True)
            continue
        except (exceptions.BlockedUser, exceptions.NSFWContent):
            update_request_to_used(request_dict["id"])
        except Exception as error:
            try:
                send_traceback_webhook(traceback.format_exc(), request_dict, published)
                logger.error(error, exc_info=True)
                exception_count += 1
                update_request_to_used(request_dict["id"])
                message = type(error).__name__
                if "offens" in message.lower():
                    block_user(request_dict["user"])
                notify(request_dict["id"], message, published)
            # We don't want the bot to stop working after notifying an
            # exception
            except Exception as error:
                logger.error(error, exc_info=True)

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

    priority_list = get_requests(filter_type, True)

    request_list = get_requests(filter_type)

    logger.info(f"Requests found in normal list: {len(request_list)}")

    if priority_list:
        logger.info(f"Requests found in priority list: {len(priority_list)}")
        if not handle_request_list(priority_list, published=not test):
            logger.info("Falling back to normal list")
            handle_request_list(request_list, published=not test)
    else:
        handle_request_list(request_list, published=not test)

    logger.info("FINISHED\n" + "#" * 70)


@click.command("post")
def publish():
    " Find a valid request and post it to Facebook. "
    kino_log(KINOLOG)
    post("episodes")
    post()


# Use a separate command instead of parameters in order to set different
# databases at runtime with sys.argv[1].
@click.command("test")
def testing():
    " Find a valid request for tests. "
    kino_log(KINOLOG + ".test")
    post(test=True)
    post("episodes", test=True)
