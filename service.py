#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import sys
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import kinobot

try:
    if "test" == sys.argv[1]:
        kinobot.KINOBASE = kinobot.KINOBASE + ".save"
        kinobot.REQUESTS_DB = kinobot.REQUESTS_DB + ".save"
        kinobot.REQUESTS_JSON = kinobot.REQUESTS_JSON + ".save"
        kinobot.KINOLOG = kinobot.KINOLOG + ".save"
        kinobot.DISCORD_WEBHOOK = kinobot.DISCORD_WEBHOOK_TEST
        TEST = True
except IndexError:
    TEST = False


from kinobot.post import get_reacts_count, post
from kinobot.utils import kino_log


CRON = "*/30 * * * *"

logger = logging.getLogger(__name__)


def post_request():
    post("episodes", TEST)
    post_id = post(test=TEST)

    logger.info(f"Waiting 10 minutes to verify Facebook reacts for {post_id}")

    time.sleep(600)

    if get_reacts_count(post_id) < 15:
        logger.info("Ignored post")
        post(test=TEST)


if __name__ == "__main__":
    kino_log(kinobot.KINOLOG)

    logger.info(f"Log location: {kinobot.KINOLOG}")
    logger.info(f"Cron: {CRON}")

    sched = BlockingScheduler()
    sched.add_job(post_request, CronTrigger.from_crontab(CRON))

    sched.start()
