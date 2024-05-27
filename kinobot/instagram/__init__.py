#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from abc import ABC
from abc import abstractmethod
from datetime import datetime
import logging
from typing import List, Optional

import pydantic
import requests

logger = logging.getLogger(__name__)

CARROUSEL = "CAROUSEL"
BASE_URL = "https://graph.facebook.com/v15.0"


class LimitExceeded(Exception):
    pass


class IGClientError(Exception):
    def __init__(self, *args: object, status_code=None) -> None:
        super().__init__(*args)

        self.status_code = status_code


class GenericResponse(pydantic.BaseModel):
    id: str


class IGFrom(pydantic.BaseModel):
    id: str
    username: str


class IGComment(pydantic.BaseModel):
    text: str
    id: str
    from_: IGFrom


class Media(pydantic.BaseModel):
    id: str
    media_type: str = "unknown"
    timestamp: datetime
    comments: List[IGComment] = []
    permalink: Optional[str] = None
    like_count: Optional[int] = None


class AbstractClient(ABC):
    @abstractmethod
    def get_media_list(self) -> List[Media]:
        raise NotImplementedError

    @abstractmethod
    def media_publish(self, creation_id):
        raise NotImplementedError

    @abstractmethod
    def get_media(self, id) -> Media:
        raise NotImplementedError

    @abstractmethod
    def any_media(self, images: List[str], caption=None) -> GenericResponse:
        """Convenience method to handle carousels and single items automatically.

        raises: LimitExceeded, requests.HTTPError"""
        raise NotImplementedError


def _catch_error(response):
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        raise IGClientError(response.text, status_code=response.status_code) from error


class Client(AbstractClient):
    def __init__(self, id, token, session=None) -> None:
        self._id = id
        self._token = token
        self._session = session or requests.Session()

    def media(
        self,
        image_url: str,
        caption=None,
        media_type=None,
        is_carousel_item=None,
    ):
        payload = {"image_url": image_url, "access_token": self._token}

        if caption is not None:
            payload["caption"] = caption

        if media_type is not None:
            payload["media_type"] = media_type

        if is_carousel_item is not None:
            payload["is_carousel_item"] = is_carousel_item

        response = self._session.post(f"{BASE_URL}/{self._id}/media", params=payload)

        _catch_error(response)

        return GenericResponse(**response.json())

    def get_media_list(self):
        params = {"access_token": self._token}
        response = self._session.get(
            f"{BASE_URL}/{self._id}/media?fields=media_type,timestamp,like_count,permalink",
            params=params,
        )
        _catch_error(response)

        return [Media(**data) for data in response.json()["data"]]

    def media_publish(self, creation_id):
        payload = {"creation_id": creation_id, "access_token": self._token}
        response = self._session.post(
            f"{BASE_URL}/{self._id}/media_publish", params=payload
        )
        _catch_error(response)

        return GenericResponse(**response.json())

    def carousel(self, image_urls, caption=None):
        if len(image_urls) > 10:
            raise LimitExceeded

        containers = []

        for image_url in image_urls:
            containers.append(self.media(image_url, is_carousel_item=True).id)

        children = ",".join(containers)

        payload = {
            "children": children,
            "caption": caption,
            "media_type": CARROUSEL,
            "access_token": self._token,
        }

        response = self._session.post(f"{BASE_URL}/{self._id}/media", params=payload)
        _catch_error(response)

        return GenericResponse(**response.json())

    def get_media(self, id):
        response = self._session.get(
            f"{BASE_URL}/{id}"
            + "?fields=media_type,comments{from,text},media_url,like_count,timestamp,permalink",
            params={"access_token": self._token},
        )
        _catch_error(response)

        data = response.json()
        try:
            comments = [
                IGComment(**item, from_=item["from"])
                for item in data["comments"]["data"]
            ]
            data.pop("comments", None)
        except KeyError:
            comments = []

        return Media(**data, comments=comments)

    def any_media(
        self, images: List[str], caption=None, publish=True
    ) -> GenericResponse:
        if len(images) > 1:
            response = self.carousel(images, caption=caption)
        else:
            response = self.media(images[0], caption=caption)

        logger.info("Uploaded: %s", response)

        if publish:
            response = self.media_publish(response.id)
            logger.info("Published: %s", response)
        else:
            logger.info("Not publishing")

        return response
