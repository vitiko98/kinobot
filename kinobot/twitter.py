#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import logging
import os
import re
import time
import sqlite3

import click
import tweepy

import kinobot
from kinobot.api import handle_request
from kinobot.comments import direct_request
from kinobot.db import (
    create_twitter_db,
    get_last_mention_id,
    get_twitter_patreon_tier,
    handle_discord_limits,
    insert_twitter_mention_id,
)
from kinobot.exceptions import KinoException, LimitExceeded
from kinobot.utils import kino_log

LOG = os.path.join(kinobot.KINOLOG_PATH, "twitter.db")

MENTIONS_RE = re.compile(r"@([^\s]+)")

PATREON = "https://patreon.com/kinobot"
HELP_WEB = "https://kino.caretas.club/requests"

REQ_DICT = {
    "gif": ["auteur", "botmin"],
    "regular": ["director", "auteur", "botmin"],
}

LIMIT_MESSAGE = (
    "Your daily limit 3 was excedeed. Support the bot and "
    f"get UNLIMITED requests becoming a Patron: {PATREON}\n"
    f"If you are already a patron, please report it via "
    "Discord or Patreon."
)

HELP = f"You can also read how to make requests: {HELP_WEB}"

logger = logging.getLogger(__name__)


def get_api_obj():
    auth = tweepy.OAuthHandler(kinobot.TWITTER_KEY, kinobot.TWITTER_SECRET)
    auth.set_access_token(
        kinobot.TWITTER_ACCESS_TOKEN, kinobot.TWITTER_ACCESS_TOKEN_SECRET
    )
    return tweepy.API(auth)


def check_roles(user_id, user_roles, req_key="regular"):
    key_roles = REQ_DICT[req_key]
    logger.info("User roles %s", user_roles)
    logger.info("Key roles %s", key_roles)
    matches = sum([role in key_roles for role in user_roles])

    logger.info("Matches: %s", matches)
    if matches:
        logger.info("Patreon found")
        return

    handle_discord_limits(user_id, 3 if req_key.lower() != "gif" else 1)


def handle_mention(mention):
    try:
        insert_twitter_mention_id(mention.id)
    except sqlite3.IntegrityError:
        pass

    tier = get_twitter_patreon_tier(mention.user.id)

    logger.info(f"Found tier for {mention.user.screen_name}: {tier}")

    # Remove mentions from tweet
    tweet = re.sub(MENTIONS_RE, "", mention.text).strip()

    logger.info(f"Tweet: {tweet}")
    if not tweet.startswith("!"):
        return

    logger.info(f"Processing tweet: {tweet}")

    request_dict = direct_request(tweet, user=mention.user.screen_name)

    if len(request_dict["content"]) > 4:
        logger.info("Long request ignored")
        return

    logger.info("Request dictionary: %s", request_dict)

    check_roles(
        mention.user.id,
        [tier or "everyone"],
        "regular" if "gif" not in request_dict["type"] else "gif",
    )

    return handle_request(request_dict, facebook=False, twitter=True)


def handle_mention_list(api, mentions):
    logger.info(f"About to handle {len(mentions)} mentions")

    for mention in mentions:
        try:
            result = handle_mention(mention)

            if not result:
                continue

            logger.info("Uploading images")
            media_list = [
                api.media_upload(image).media_id for image in result["images"]
            ]
            head = f"{result['description']}\nRequester: @{mention.user.screen_name}"
            description = head.replace("\n\n", "\n")[:280]

            logger.info(f"Description: {description}")

            api.update_status(
                status=description,
                in_reply_to_status_id=mention.id,
                auto_populate_reply_metadata=True,
                media_ids=media_list,
            )
            logger.info("Tweeted")
        except LimitExceeded:
            message = f"@{mention.user.screen_name} {LIMIT_MESSAGE}"
            api.update_status(status=message, in_reply_to_status_id=mention.id)
            logger.info("Limit excedeed notified")
        except KinoException as error:
            # If exception message is empty
            if not error:
                continue
            message = f"@{mention.user.screen_name} Error! {error}\n{HELP}"
            logger.info(f"Notification for error: {message}")
            api.update_status(status=message, in_reply_to_status_id=mention.id)

        except Exception as error:
            logger.error(error, exc_info=True)


def watch_mentions():
    logger.info("Starting mention watcher")
    # Maybe it's better to initialize this before (?)
    api = get_api_obj()
    last_mention = get_last_mention_id()
    logger.info(f"Last mention: {last_mention}")

    mentions = api.mentions_timeline(since_id=last_mention, count=100)
    if not mentions:
        logger.info("No new mentions found")
        return

    handle_mention_list(api, mentions)


@click.command("twitter")
def start_twitter_loop():
    " Start Twitter bot loop. "
    kino_log(LOG)
    create_twitter_db()
    try:
        while True:
            try:
                watch_mentions()
            # TODO: remove this catch ASAP!
            except Exception as error:
                logger.error(error, exc_info=True)
            time.sleep(45)
    except KeyboardInterrupt:
        logger.info("Interrupted")
