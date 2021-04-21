#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import datetime
import json
import logging
from typing import Any, List, Optional

from facepy import GraphAPI

from .constants import FACEBOOK_TOKEN, FACEBOOK_URL
from .db import Kinobase
from .exceptions import RecentPostFound
from .frame import Static

logger = logging.getLogger(__name__)


class Post(Kinobase):
    """Base class for Facebook posts."""

    table = "posts"
    _insertables = ("id", "content", "reacts")

    def __init__(
        self,
        token: Optional[str] = None,
        page: Optional[str] = None,
        published: bool = False,
        **kwargs,
    ):
        self.page = page or FACEBOOK_URL
        self.token = token or FACEBOOK_TOKEN
        self.published = published
        self.id = None
        self.content = None
        self.reacts = 0
        self.added = None
        self.posted = False

        self._set_attrs_to_values(kwargs)

        self.images: List[str] = []

        self._api = GraphAPI(self.token)
        self._description = None

    def register(self):
        " Register the post in the database. "
        # assert self.posted and self.published
        assert self.content is not None

        self._insert()

    def post(self, handler: Static):
        """Process a request with a handler and post it to Facebook.

        :param handler:
        :type handler: Static
        :raises exceptions.RecentPostFound
        """
        if self.published and self.recently_posted():
            raise RecentPostFound

        self.images = handler.get()
        self.content = handler.content
        self._description = handler.title

        if len(self.images) == 1:
            self._post_single()
        else:
            self._post_multiple()

    def comment(
        self, content: str, parent_id: Optional[str] = None, image: Optional[str] = None
    ):
        """Make a post comment. If parent_id is not set, comment to the class ID.

        :param content:
        :type content: str
        :param parent_id:
        :type parent_id: Optional[str]
        :param image:
        :type image: Optional[str]
        """
        assert self.posted
        parent_id = parent_id or self.id

        params: dict[str, Any] = {
            "path": f"{parent_id}/comments",
            "message": content,
            "published": self.published,
        }

        if image is not None:
            logger.debug("Adding image to comment: %s", image)
            params["source"] = open(image, "rb")

        comment = self._api.post(**params)
        if isinstance(comment, dict):
            logger.info("Comment posted: %s", comment["id"])

    def recently_posted(self) -> bool:
        posts = self._api.get("me/posts", limit=1)

        if isinstance(posts, dict):
            time_ = posts["data"][0]["created_time"]
            post_dt = datetime.datetime.strptime(time_, "%Y-%m-%dT%H:%M:%S+0000")
            now_dt = datetime.datetime.now(tz=datetime.timezone.utc)

            logger.info("Last post and now timedates: %s", ((post_dt, now_dt)))

            diff = abs(post_dt.timestamp() - now_dt.timestamp())

            if diff > 300:
                logger.info("No recent posts found with %s seconds of ditance", diff)
                return False

            logger.info("Recent post found with %s seconds of distance", diff)
            return True

        return False

    def _post_multiple(self):
        assert len(self.images) > 1

        ids = []
        for image in self.images:
            logger.info("Uploading image: %s", image)
            post = self._api.post(
                path="me/photos", source=open(image, "rb"), published=self.published
            )
            if isinstance(post, dict):
                ids.append({"media_fbid": post["id"]})

        attached_media = json.dumps(ids)

        post = self._api.post(
            path="me/feed",
            attached_media=attached_media,
            message=self._description,
            published=self.published,
        )

        if isinstance(post, dict):
            self.id = post["id"]
            self.posted = True
            logger.info("Posted: %s/posts/%s", self.page, self.id.split("_")[-1])

    def _post_single(self):
        assert len(self.images) == 1
        logger.info("Posting single image")

        post = self._api.post(
            path="me/photos",
            source=open(self.images[0], "rb"),
            published=self.published,
            message=self._description,
        )

        if isinstance(post, dict):
            self.id = post["id"]
            self.posted = True
            logger.info("Posted: %s/photos/%s", self.page, self.id)
