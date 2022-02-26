#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging

from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .badge import Badge
from .constants import (
    FACEBOOK_URL,
    FACEBOOK_URL_ES,
    FACEBOOK_URL_PT,
    FACEBOOK_URL_MAIN,
)
from .db import Execute
from .exceptions import KinoException, NothingFound, RecentPostFound
from .poster import FBPoster, FBPosterPt, FBPosterEs
from .register import EpisodeRegister, FacebookRegister, MediaRegister
from .request import Request, RequestEs, RequestPt, RequestMain
from .utils import handle_general_exception

logger = logging.getLogger(__name__)

sched = BlockingScheduler()


@sched.scheduled_job(CronTrigger.from_crontab("*/30 * * * *"))  # every 30 min
def collect_from_facebook(posts: int = 40):
    """Collect new requests and ratings from the Facebook page.

    :param posts:
    :type posts: int
    """
    for identifier in ("en", "es", "pt"):
        register = FacebookRegister(posts, identifier)
        register.requests()
        register.ratings()
        # Rest a bit from API calls
        # logger.info("Sleeping 60 minutes before registering badges")
        # time.sleep(60)
        # register.badges()


@sched.scheduled_job(CronTrigger.from_crontab("0 0 * * *"))  # every midnight
def reset_discord_limits():
    "Reset role limits for Discord users."
    Execute().reset_limits()


@sched.scheduled_job(CronTrigger.from_crontab("*/30 * * * *"))  # every 30 min
def update_badges():
    "Update or insert the registered badges in the database."
    Badge.update_all()


def _post_to_facebook(identifier="en"):
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

        try:
            poster = poster_cls(request, fb_url)
            poster.handle()
            poster.comment()
            break

        except RecentPostFound as error:
            logger.error(error)
            break

        except KinoException as error:
            logger.error(error)
            if count < 4:
                continue

            logger.debug("KinoException limit exceeded")
            break


_request_poster_map = {RequestEs: FBPosterEs, RequestPt: FBPosterPt}
_req_cls_map = {"es": RequestEs, "pt": RequestPt, "main": RequestMain}
_fb_url_map = {
    "en": FACEBOOK_URL,
    "es": FACEBOOK_URL_ES,
    "pt": FACEBOOK_URL_PT,
    "main": FACEBOOK_URL_MAIN,
}


@sched.scheduled_job(CronTrigger.from_crontab("0 * * * *"))  # every 30 min
def post_to_facebook():
    "Find a valid request and post it to Facebook."
    for identifier in ("en", "es", "pt", "main"):
        _post_to_facebook(identifier)


@sched.scheduled_job(CronTrigger.from_crontab("0 */2 * * *"))  # every even hour
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

    if not isinstance(exception, KinoException):
        handle_general_exception(exception)


sched.add_listener(error_listener, EVENT_JOB_ERROR)
