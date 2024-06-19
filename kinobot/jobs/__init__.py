#!/usr/bin/env python3,
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import datetime
import logging

from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from . import fb
from ..config import config
from ..constants import YAML_CONFIG
from ..db import Execute
from ..exceptions import KinoException
from ..exceptions import NothingFound
from ..exceptions import RecentPostFound
from ..misc import anime
from ..misc import bonus
from ..post import register_posts_metadata
from ..poster import FBPoster
from ..register import EpisodeRegister
from ..register import FacebookRegister
from ..register import MediaRegister
from ..request import Request
from ..utils import get_yaml_config
from ..utils import handle_general_exception
from ..utils import send_webhook
from ..utils import sync_local_subtitles

logger = logging.getLogger(__name__)

sched = BlockingScheduler(timezone=pytz.timezone("US/Eastern"))
fb_sched = BlockingScheduler(timezone=pytz.timezone("US/Eastern"))

sched.add_job(sync_local_subtitles, CronTrigger.from_crontab("*/30 * * * *"))
# sched.add_job(announcements.top_contributors, "cron", hour="10,20", minute=0, second=0)


@sched.scheduled_job(CronTrigger.from_crontab("*/30 * * * *"))  # every 30 min
def collect_from_facebook(posts: int = 40):
    """Collect new requests and ratings from the Facebook page.

    :param posts:
    :type posts: int
    """
    for identifier in ("en",):
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

        if count < 5:
            continue

        logger.debug("KinoException limit exceeded")
        break

    logger.info("Post loop [%s] finished", identifier)


def _run_req(poster_cls, request, fb_url, retry=2):
    logger.info("Running %s [%s]", request, request.id)

    mark = True
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

        except Exception as error:
            logger.error(error, exc_info=True)
            mark = False
            break

    if mark:
        request.mark_as_used()
        logger.info("Marking as used: %s", request)
        send_webhook(
            config.webhooks.announcer,
            f"This request was marked as used due to internal errors: {request.pretty_title}\n\nID: {request.id}",
        )
    return False


_request_poster_map = {}
_req_cls_map = {}  # "es": RequestEs, "pt": RequestPt, "main": RequestMain}
_fb_url_map = {
    "en": "",
    #    "es": FACEBOOK_URL_ES,
    #    "pt": FACEBOOK_URL_PT,
    "main": "",
}


@sched.scheduled_job(CronTrigger.from_crontab("0 */6 * * *"), misfire_grace_time=None)
def scan_posts_metadata():
    from_ = datetime.datetime.now() - datetime.timedelta(days=20)
    to_ = datetime.datetime.now() - datetime.timedelta(hours=12)

    config = get_yaml_config(YAML_CONFIG, "facebook")  # type: ignore

    for key, val in config.items():
        logger.info("Scanning insights from '%s'", key)
        register_posts_metadata(
            val["insights_token"],
            from_=from_,
            to_=to_,
            ignore_non_zero_impressions=False,
        )

    bonus.run()


@sched.scheduled_job(CronTrigger.from_crontab("0 * * * *"))
def post_to_ig():
    from kinobot.discord.instagram import ig_poster
    from kinobot.discord.instagram import make_post

    ig_poster()


# @fb_sched.scheduled_job(
#    CronTrigger.from_crontab("*/30 * * * *"), misfire_grace_time=None
# )  # every 30 min
def post_to_facebook():
    "Find a valid request and post it to Facebook."
    for identifier in ("en",):
        _post_to_facebook(identifier)


# @sched.scheduled_job(CronTrigger.from_crontab("0 */3 * * *"))
def anime_():
    anime.handle_downloaded()
    anime.scan_subs()


@sched.scheduled_job(CronTrigger.from_crontab("0 * * * *"))  # every hour
def register_media():
    "Register new media in the database."
    for media in (MediaRegister, EpisodeRegister):
        try:
            handler = media(only_w_subtitles=False)

            try:
                handler.load_new_and_deleted()
                handler.handle()
            except Exception as error:
                logger.error(error, exc_info=True)
                continue
        except Exception as error:
            logger.error(error)
            continue


def error_listener(event):
    exception = event.exception

    logger.error(exception, exc_info=True)

    if not isinstance(exception, KinoException):
        try:
            handle_general_exception(exception)
        except Exception as error:
            logger.error(error)


sched.add_listener(error_listener, EVENT_JOB_ERROR)


def _add_posters():
    try:
        for poster in fb.get_posters():
            fb_sched.add_job(
                fb.post_func,
                kwargs=poster,
                misfire_grace_time=None,
                trigger=poster["cron_trigger"],
                id=poster["name"],
            )
            logger.info("Added job: %s", poster)
    except Exception as error:
        logger.error(error)


_add_posters()
