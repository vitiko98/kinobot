import logging

from apscheduler.triggers.cron import CronTrigger

from kinobot.config import config
from kinobot.exceptions import KinoException
from kinobot.exceptions import NothingFound
from kinobot.post import Post
from kinobot.poster import FBPoster as Poster
from kinobot.request import Request
from kinobot.utils import send_webhook

logger = logging.getLogger(__name__)


def _req_factory(name):
    if name == "main":
        return Request.random_from_queue(verified=True)

    return Request.random_from_queue(verified=True, tag=name)


def get_posters():
    for item in config.posters.instances:
        if not item.enabled:
            logger.info("Ignoring %s [DISABLED]", item["page"])
            continue

        def run_poster():
            return _post_to_facebook(
                Post(item, published=config.posters.published), item.name
            )

        yield {
            "run_poster": run_poster,
            "cron_trigger": CronTrigger.from_crontab(item.scheduler),
            "name": item.name,
        }


def _post_to_facebook(post_instance, name):
    logger.info("Starting post loop [%s]", name)

    count = 0
    while True:
        count += 1

        try:
            request = _req_factory(name)
        except NothingFound:
            logger.info("No new requests found")
            break

        ran = _run_req(Poster, request, post_instance, retry=2)
        if ran:
            break

        if count < 5:
            continue

        logger.debug("KinoException limit exceeded")
        break

    logger.info("Post loop [%s] finished", name)


def _run_req(poster_cls, request, post_instance, retry=2):
    logger.info("Running %s [%s]", request, request.id)

    mark = True
    for n in range(retry):
        try:
            poster = poster_cls(request, post_instance)
            poster.handle()
            poster.comment()
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
