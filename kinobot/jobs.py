#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import datetime
import logging
import os
import subprocess

from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .constants import (
    DISCORD_ANNOUNCER_WEBHOOK,
    FACEBOOK_INSIGHTS_TOKEN,
    FACEBOOK_URL,
    FACEBOOK_URL_ES,
    FACEBOOK_URL_MAIN,
    FACEBOOK_URL_PT,
)
from .db import Execute
from .exceptions import KinoException, NothingFound, RecentPostFound
from .post import register_posts_metadata
from .poster import FBPoster, FBPosterEs, FBPosterPt
from .register import EpisodeRegister, FacebookRegister, MediaRegister
from .request import Request, RequestEs, RequestMain, RequestPt
from .utils import handle_general_exception, send_webhook, sync_local_subtitles

logger = logging.getLogger(__name__)

sched = BlockingScheduler()

sched.add_job(sync_local_subtitles, CronTrigger.from_crontab("*/30 * * * *"))


@sched.scheduled_job(CronTrigger.from_crontab("*/30 * * * *"))  # every 30 min
def collect_from_facebook(posts: int = 40):
    """Collect new requests and ratings from the Facebook page.

    :param posts:
    :type posts: int
    """
    for identifier in ("en", "es", "pt"):
        register = FacebookRegister(posts, identifier)
        register.requests()


#        register.ratings()


@sched.scheduled_job(CronTrigger.from_crontab("0 0 * * *"))  # every midnight
def reset_discord_limits():
    "Reset role limits for Discord users."
    Execute().reset_limits()


def _post_to_facebook(identifier="en"):
    logger.info("Starting post loop [%s]", identifier)

    request_cls = _req_cls_map.get(identifier, Request)

    try:
        fb_url = _fb_url_map[identifier]
    except KeyError:
        raise ValueError(f"{identifier} not found in registry")

    poster_cls = _request_poster_map.get(request_cls, FBPoster)  # type: ignore

    count = 0
    while True:
        count += 1

        try:
            request = request_cls.random_from_queue(verified=True)
        except NothingFound:
            logger.info("No new requests found")
            break

        ran = _run_req(poster_cls, request, fb_url, retry=2)
        if ran:
            break

        if count < 4:
            continue

        logger.debug("KinoException limit exceeded")
        break

    logger.info("Post loop [%s] finished", identifier)


def _run_req(poster_cls, request, fb_url, retry=2):
    for n in range(retry):
        try:
            poster = poster_cls(request, fb_url)
            poster.handle()
            poster.comment()
            return True

        except RecentPostFound as error:
            logger.error(error)
            return True

        except KinoException as error:
            logger.error(error, exc_info=True)
            logger.info("Trying again... [%d]", n)
            continue

    request.mark_as_used()
    logger.info("Marking as used: %s", request)
    send_webhook(
        DISCORD_ANNOUNCER_WEBHOOK,
        f"This request was marked as used due to internal errors: {request.pretty_title}\n\nID: {request.id}",
    )
    return False


_request_poster_map = {RequestEs: FBPosterEs, RequestPt: FBPosterPt}
_req_cls_map = {"es": RequestEs, "pt": RequestPt, "main": RequestMain}
_fb_url_map = {
    "en": FACEBOOK_URL,
    "es": FACEBOOK_URL_ES,
    "pt": FACEBOOK_URL_PT,
    "main": FACEBOOK_URL_MAIN,
}


@sched.scheduled_job(CronTrigger.from_crontab("*/30 * * * *"))  # every 30 min
def scan_posts_metadata():
    from_ = datetime.datetime.now() - datetime.timedelta(weeks=3)
    to_ = datetime.datetime.now() - datetime.timedelta(hours=12)

    register_posts_metadata(
        FACEBOOK_INSIGHTS_TOKEN, from_=from_, to_=to_, ignore_non_zero_impressions=False
    )


@sched.scheduled_job(CronTrigger.from_crontab("*/30 * * * *"))  # every 30 min
def post_to_facebook():
    "Find a valid request and post it to Facebook."
    for identifier in ("en", "es", "pt", "main"):
        _post_to_facebook(identifier)


@sched.scheduled_job(CronTrigger.from_crontab("0 * * * *"))  # every hour
def register_media():
    "Register new media in the database."
    for media in (MediaRegister, EpisodeRegister):
        handler = media(only_w_subtitles=False)

        try:
            handler.load_new_and_deleted()
            handler.handle()
        except Exception as error:
            logger.debug("%s raised for %s. Ignoring", error, media)
            continue


def error_listener(event):
    exception = event.exception

    logger.error(exception, exc_info=True)

    if not isinstance(exception, KinoException):
        handle_general_exception(exception)


sched.add_listener(error_listener, EVENT_JOB_ERROR)
