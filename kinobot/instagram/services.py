from datetime import datetime
from datetime import timedelta
import logging
from typing import Callable, Optional

import requests

from kinobot.instagram import AbstractClient

from . import events
from . import models
from .db import PostRepository
from .templates import render

logger = logging.getLogger(__name__)


def _is_interval_acceptable(
    last_record: datetime, reference: datetime, interval: timedelta
):
    if last_record > reference:
        logger.debug("Last record is newer than reference. Returning False.")
        return False

    record_interval = reference - last_record
    acceptable = record_interval >= interval
    logger.debug(
        "Acceptable? '%s' -> '%s' (interval:%s) ::: %s",
        last_record,
        reference,
        interval,
        acceptable,
    )
    return acceptable


class NotAcceptableToPost(Exception):
    pass


class Handler:
    def __init__(self, host, api_key) -> None:
        self._host = host
        self._api_key = api_key
        self._session = requests.Session()

    def request(self, content):
        response = self._session.get(
            f"{self._host}/request",
            params={"api_key": self._api_key, "content": content},
        )
        response.raise_for_status()

        return models.FinishedRequest.parse_obj(response.json())


req_picker = Callable[..., models.Request]
handler = Callable[[str], models.FinishedRequest]


def is_acceptable_interval(client, post_repo, acceptable_interval):
    if acceptable_interval is not None:
        logger.debug("Getting last post")
        try:
            datetimes = [client.get_media_list()[0].timestamp]
        except IndexError:
            datetimes = []

        try:
            last_db_post = post_repo.get_last()
            if last_db_post:
                datetimes.append(last_db_post.added)
        except:
            pass

        acceptable = True
        for dt in datetimes:
            acceptable = _is_interval_acceptable(
                dt, datetime.utcnow(), acceptable_interval
            )

        if not acceptable:
            raise NotAcceptableToPost(f"{acceptable_interval} -> {datetimes}")


def post(
    client: AbstractClient,
    picker: req_picker,
    req_handler: handler,
    renderer: Optional[Callable[..., str]] = None,
    event_publisher=None,
):
    "raises NotAcceptableToPost"
    request_ = picker()
    if request_ is None:
        logger.info("No requests to post from %s", picker)
        return None

    logger.info("Got request: %s", request_)
    finished_request = req_handler(request_.content)
    caption = (renderer or render)(finished_request, request_)
    response = client.any_media(finished_request.image_uris, caption)
    media = client.get_media(response.id)

    if event_publisher is not None:
        event_publisher(
            events.PostCreated(
                finished_request=finished_request,
                request=request_,
                ig_id=response.id,
                caption=caption,
                permalink=media.permalink,
            )
        )

    return response
