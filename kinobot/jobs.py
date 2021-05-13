#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import time

from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .badge import Badge
from .constants import DISCORD_TRACEBACK_WEBHOOK
from .db import Execute
from .exceptions import KinoException, NothingFound, RecentPostFound
from .poster import FBPoster
from .register import FacebookRegister, MediaRegister
from .request import Request
from .utils import fmt_exception, send_webhook

logger = logging.getLogger(__name__)

sched = BlockingScheduler()


@sched.scheduled_job(CronTrigger.from_crontab("*/30 * * * *"))  # every 30 min
def collect_from_facebook(posts: int = 40):
    """Collect new requests and ratings from the Facebook page.

    :param posts:
    :type posts: int
    """
    register = FacebookRegister(posts)
    register.requests()
    register.ratings()
    # Rest a bit from API calls
    logger.info("Sleeping 60 minutes before registering badges")
    time.sleep(60)
    register.badges()


@sched.scheduled_job(CronTrigger.from_crontab("0 0 * * *"))  # every midnight
def reset_discord_limits():
    " Reset role limits for Discord users. "
    excecute = Execute()
    excecute.reset_limits()


@sched.scheduled_job(CronTrigger.from_crontab("*/30 * * * *"))  # every 30 min
def update_badges():
    " Update or insert the registered badges in the database. "
    Badge.update_all()


@sched.scheduled_job(CronTrigger.from_crontab("*/30 * * * *"))  # every 30 min
def post_to_facebook():
    " Find a valid request and post it to Facebook. "
    count = 0
    while True:
        count += 1

        try:
            request = Request.random_from_queue(verified=True)
        except NothingFound:
            logger.info("No new requests found")
            break

        try:
            poster = FBPoster(request)
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


@sched.scheduled_job(CronTrigger.from_crontab("0 */2 * * *"))  # every even hour
def register_media():
    " Register new media in the database (currently only movies). "
    handler = MediaRegister(only_w_subtitles=True)
    handler.load_new_and_deleted()
    handler.handle()


def error_listener(event):
    exception = event.exception

    if not isinstance(exception, KinoException):
        send_webhook(DISCORD_TRACEBACK_WEBHOOK, fmt_exception(exception))


sched.add_listener(error_listener, EVENT_JOB_ERROR)
