from abc import ABC
from abc import abstractmethod
from datetime import timedelta
import logging
import os
import shutil
from typing import List, Optional, Union
import uuid

from pydantic import BaseModel, ConfigDict
from pydantic.fields import Field

from kinobot.exceptions import KinoException
from kinobot.media import Episode, Movie
from kinobot.request import Request
from kinobot.item import RequestItem

logger = logging.getLogger(__name__)


class MediaItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Union[str, int]
    pretty_title: str
    simple_title: str
    parallel_title: str
    sub_title: Optional[str] = None
    type: str
    keywords: List[str] = []


class Subtitle(BaseModel):
    index: int
    content: str
    timestamp: timedelta = Field(alias="start")
    model_config = ConfigDict(from_attributes=True)


class Bracket(BaseModel):
    index: Optional[int] = None
    subtitle_quote: Optional[str] = None
    raw: str
    type: str


class RequestData(BaseModel):
    type: str
    comment: str
    model_config = ConfigDict(from_attributes=True)


class FinishedRequest(BaseModel):
    media_items: List[MediaItem]
    request_data: RequestData
    image_uris: List[str]
    model_config = ConfigDict(from_attributes=True)


transporters = {}


def register(key):
    def decorator(cls):
        transporters[key] = cls
        return cls

    return decorator


class ImageTransporter(ABC):
    _config: dict

    @abstractmethod
    def transport(self, images: List[str]) -> List[str]:
        pass


class TransporterException(Exception):
    pass


@register("dummy")
class DummyImageTransporter(ImageTransporter):
    def __init__(self, config=None) -> None:
        self._config = config or {}

    def transport(self, images: List[str]):
        return images


@register("local_server")
class LocalServerImageTransporter(ImageTransporter):
    def __init__(self, config=None) -> None:
        config = config or {}
        self._host = config["host"].rstrip("/")
        self._output_dir = config["output_dir"]

        if not os.access(self._output_dir, os.W_OK):
            raise TransporterException(f"{self._output_dir} is not accessible")

    def transport(self, images: List[str]):
        transported = []
        for img in images:
            name = str(uuid.uuid4()) + os.path.splitext(img)[-1]
            new_path = os.path.join(self._output_dir, name)

            shutil.copy(img, new_path)

            url = f"{self._host}/{name}"

            logger.debug("Copied: %s -> %s [URL: %s]", img, new_path, url)
            transported.append(url)

        return transported


def process_request(content: str, transporter: ImageTransporter) -> FinishedRequest:
    "A proxy of the abomination from requests.Request"
    logger.debug("About to inject content into request: '%s'", content)
    req = Request(content, "foo", "1", "foo")
    logger.debug("Getting handler...")

    handler = req.get_handler()

    logger.debug("Getting images")

    image_uris = transporter.transport(handler.get())

    media_items = []
    for item in handler.items:
        media_items.append(MediaItem.from_orm(item.media))

    request_data = RequestData.from_orm(req)

    return FinishedRequest(
        media_items=media_items, request_data=request_data, image_uris=image_uris
    )


def media_search(query: str):
    items = Movie.from_query_many(query)

    if not items:
        items = [Episode.from_query(query)]

    return [MediaItem.from_orm(item) for item in items]


def _get_computed(item, query):
    req_item = RequestItem(item, [query])
    req_item.compute_brackets()
    results = []
    for bracket in req_item.brackets:
        results.append(
            Bracket(
                index=bracket.subtitle_index,
                subtitle_quote=bracket.subtitle_quote,
                raw=query,
                type="computed",
            )
        )

    return results


def subtitle_search(id: str, query):
    try:
        item = Movie.from_id(id)
    except KinoException:
        item = Episode.from_id(id)

    try:
        computed_results = _get_computed(item, query)
    except KinoException as error:
        logger.error(error, exc_info=True)
        computed_results = []

    if not computed_results:
        results = item.search_subs(query)
        for result in results:
            computed_results.append(
                Bracket(
                    index=result.index,
                    subtitle_quote=result.content,
                    raw=query,
                    type="partial",
                )
            )

    return computed_results
