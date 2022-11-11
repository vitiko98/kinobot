#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import List

import pydantic
import requests

CARROUSEL = "CAROUSEL"
BASE_URL = "https://graph.facebook.com/v15.0"


class LimitExceeded(Exception):
    pass


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
    media_type: str
    comments: List[IGComment]
    like_count: int


class Client:
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
        response.raise_for_status()

        return GenericResponse(**response.json())

    def media_publish(self, creation_id):
        payload = {"creation_id": creation_id, "access_token": self._token}
        response = self._session.post(
            f"{BASE_URL}/{self._id}/media_publish", params=payload
        )
        return response.json()

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
        return GenericResponse(**response.json())

    def get_media(self, id):
        response = self._session.get(
            f"{BASE_URL}/{id}"
            + "?fields=media_type,comments{from,text},media_url,like_count",
            params={"access_token": self._token},
        )
        response.raise_for_status()

        data = response.json()
        comments = [
            IGComment(**item, from_=item["from"]) for item in data["comments"]["data"]
        ]

        data.pop("comments")

        return Media(**data, comments=comments)
