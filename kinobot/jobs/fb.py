import datetime
import logging
from typing import Callable

from apscheduler.triggers.cron import CronTrigger

from kinobot.config import config
from kinobot.exceptions import KinoException
from kinobot.exceptions import NothingFound
from kinobot.post import Post
from kinobot.poster import FBPoster as Poster
from kinobot.request import Request
from kinobot.utils import send_webhook

from ._events import NoRequestsFound
from ._events import RequestPosted

logger = logging.getLogger(__name__)


def _req_factory(tag_):
    logger.info("Request factory: %s", tag_)
    return Request.random_from_queue(verified=True, tag=tag_)


def get_posters():
    for item in config.posters.instances:
        if not item.enabled:
            logger.info("Ignoring %s [DISABLED]", item["page"])
            continue

        yield {
            "post_instance": Post(item, published=config.posters.published),
            "cron_trigger": CronTrigger.from_crontab(item.scheduler),
            "name": item.name,
            "tag": item.tag,
        }


def post_func(post_instance, **kwargs):
    return _post_to_facebook(post_instance, **kwargs)


def _post_to_facebook(
    post_instance: Post,
    name,
    tag,
    run_req=None,
    event_handler: Callable = lambda i: None,
    **kwargs,
):
    logger.info("Starting post loop [%s]", name)

    count = 0
    while True:
        count += 1

        try:
            request = _req_factory(tag or None)
        except NothingFound:
            logger.info("No new requests found")
            event_handler(NoRequestsFound(name=name, tag=tag))
            break

        ran = (run_req or _run_req)(Poster, request, post_instance, retry=2)
        if ran:
            try:
                request.load_user()
            except:
                pass

            event_handler(
                RequestPosted(
                    request.id,
                    request.user_id,
                    request.user.name,
                    post_instance.id,
                    post_instance.facebook_url,
                )
            )
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
