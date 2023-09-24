from abc import ABC
from abc import abstractmethod
import logging
import os
import shutil
from typing import List, Optional
import uuid

from pydantic import BaseModel

from kinobot.request import Request

logger = logging.getLogger(__name__)


class MediaItem(BaseModel):
    id: str
    pretty_title: str
    simple_title: str
    parallel_title: str
    sub_title: Optional[str] = None
    type: str
    keywords: List[str] = []

    class Config:
        orm_mode = True


class RequestData(BaseModel):
    type: str
    comment: str

    class Config:
        orm_mode = True


class FinishedRequest(BaseModel):
    media_items: List[MediaItem]
    request_data: RequestData
    image_uris: List[str]


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
