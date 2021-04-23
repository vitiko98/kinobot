#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging

from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .constants import DISCORD_TRACEBACK_WEBHOOK
from .db import Execute
from .exceptions import KinoException
from .register import FacebookRegister
from .utils import fmt_exception, send_webhook

logger = logging.getLogger(__name__)

sched = BlockingScheduler()


@sched.scheduled_job(CronTrigger.from_crontab("*/30 * * * *"))  # every 30 min
def collect_from_facebook(posts: int = 1):
    """Collect new requests and ratings from the Facebook page.

    :param posts:
    :type posts: int
    """
    register = FacebookRegister(posts)
    register.requests()
    register.ratings()


@sched.scheduled_job(CronTrigger.from_crontab("0 0 * * *"))  # every midnight
def reset_discord_limits():
    " Reset role limits for Discord users. "
    excecute = Execute()
    excecute.reset_limits()


def error_listener(event):
    exception = event.exception

    if not isinstance(exception, KinoException):
        send_webhook(DISCORD_TRACEBACK_WEBHOOK, fmt_exception(exception))


sched.add_listener(error_listener, EVENT_JOB_ERROR)
