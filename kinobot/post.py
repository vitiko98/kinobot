#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import datetime
import json
import logging
from functools import cached_property
from typing import Any, List, Optional, Union

from facepy import GraphAPI

from .constants import FACEBOOK_INSIGHTS_TOKEN, FACEBOOK_TOKEN, FACEBOOK_URL
from .db import Kinobase
from .exceptions import NothingFound, RecentPostFound

logger = logging.getLogger(__name__)


class Post(Kinobase):
    " Class for Facebook posts. "

    table = "posts"
    __insertables__ = ("id", "content")

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
        self.parent_id = None
        self.content = None
        self.added = None
        self.posted = False

        self._set_attrs_to_values(kwargs)

        self._images: List[str] = []

        self._api = GraphAPI(self.token)
        self._description = None

    def register(self, content: str):
        " Register the post in the database. "
        self.content = content
        self._insert()

    def post(self, description: str, images: List[str] = None):
        """Post the images on Facebook.

        :param description:
        :type description: str
        :param images:
        :type images: List[str]
        """
        self._images = images or []  # Could be a fact post

        if self.published and self.recently_posted():
            raise RecentPostFound

        self._description = description

        if len(self._images) == 1:
            self._post_single()
        else:
            self._post_multiple()

    def comment(
        self, content: str, parent_id: Optional[str] = None, image: Optional[str] = None
    ) -> Union[str, None]:
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
            return comment["id"]

        return None

    def recently_posted(self) -> bool:
        """Find out if a post has been posted 5 minutes ago.

        :rtype: bool
        """
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

    def get_reacts_and_shares(self) -> tuple:
        """Get the amount of reacts and shares of the post.

        :rtype: int
        :raises exceptions.NothingFound
        """
        post_id = self.parent_id or self.id
        reacts = [
            "reactions.type(LIKE).limit(0).summary(true).as(like)",
            "reactions.type(LOVE).limit(0).summary(true).as(love)",
            "reactions.type(WOW).limit(0).summary(true).as(wow)",
            "reactions.type(HAHA).limit(0).summary(true).as(haha)",
            "reactions.type(SAD).limit(0).summary(true).as(sad)",
            "reactions.type(ANGRY).limit(0).summary(true).as(angry)",
            "reactions.type(THANKFUL).limit(0).summary(true).as(thankful)",
        ]
        result = self._api.get(f"{post_id}?fields={','.join(reacts)},shares")
        rcts = 0
        if isinstance(result, dict):
            for react in ("like", "love", "wow", "haha", "sad", "angry", "thankful"):
                rcts += result.get(react, {}).get("summary", {}).get("total_count", 0)

            shares = result.get("shares", {}).get("count", 0)
            return rcts, shares

        raise NothingFound

    def get_comments(self) -> int:
        """Get the amount of comments of the post.

        :rtype: int
        :raises exceptions.NothingFound
        """
        comments = self._api.get(f"{self.parent_id or self.id}/comments", limit=100)
        if isinstance(comments, dict):
            return len(comments["data"])

        raise NothingFound

    def get_engagements(self) -> tuple:
        """Get the amount of views and clicks of the post.

        :rtype: Tuple[int, int]
        """
        metrics = "post_impressions,post_clicks"
        url = f"{self.parent_id or self.id}/insights?metric={metrics}"

        self._api.oauth_token = FACEBOOK_INSIGHTS_TOKEN  # Workaround
        result = self._api.get(url)

        if isinstance(result, dict):
            values = [item["values"][0]["value"] for item in result["data"]]
            return tuple(values)

        raise NothingFound

    @cached_property
    def user_id(self) -> str:
        """User ID associated with the post.

        :rtype: str
        :raises exceptions.NothingFound
        """
        result = self._fetch(
            "select user_id from user_badges where post_id=? limit 1", (self.id,)
        )
        if not result:
            raise NothingFound

        return result[0]

    @property
    def facebook_url(self) -> str:
        """The absolute Facebook url of the post.

        :rtype: str
        """
        if self.id is not None and "_" in self.id:
            return f"{self.page}/posts/{self.id.split('_')[-1]}"

        return f"{self.page}/photos/{self.id}"

    def _post_multiple(self):
        assert len(self._images) > 1

        ids = []
        for image in self._images:
            logger.info("Uploading image: %s", image)
            post = self._api.post(
                path="me/photos", source=open(image, "rb"), published=False
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
            logger.info("Posted: %s", self.facebook_url)

    def _post_single(self):
        assert len(self._images) == 1
        logger.info("Posting single image")

        post = self._api.post(
            path="me/photos",
            source=open(self._images[0], "rb"),
            published=self.published,
            message=self._description,
        )

        if isinstance(post, dict):
            self.id = post["id"]
            self.posted = True
            logger.info("Posted: %s", self.facebook_url)
