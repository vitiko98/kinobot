#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import datetime
import json
import logging
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Union

from facepy import FacepyError
from facepy import GraphAPI
from pydantic import BaseModel

from .constants import KINOBASE
from .db import Kinobase
from .db import sql_to_dict
from .exceptions import RecentPostFound

logger = logging.getLogger(__name__)


class Post(Kinobase):
    "Class for Facebook posts."

    __insertables__ = "id"

    def __init__(
        self,
        config: Dict,
        registry_callback: Optional[Callable] = None,
        published: bool = False,
    ):
        self._config = config
        self.published = published
        self._callback = registry_callback
        self.posted = False
        self._page = config["page"]
        self._table = config["table"]
        self._images = []
        self._description = []

        if not config["token"]:
            raise ValueError("Invalid token")

        self._api = GraphAPI(config["token"])
        self._description = None
        self.id = None

    def register(self, request_id, post_id=None):
        #        if self._callback is None:
        # fixme
        return self._register(request_id)

    #       return self._callback(request_id, post_id)

    def _register(self, request_id):
        "Register the post in the database."
        self._execute_sql(
            f"insert into posts (id,request_id) values (?,?);",
            (self.id, request_id),
        )

    def get_database_dict(self):
        return self._sql_to_dict(f"select * from posts where id=?", (self.id,))[0]

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
        return False
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

    @property
    def facebook_url(self) -> str:
        """The absolute Facebook url of the post.

        :rtype: str
        """
        if self.id is not None and "_" in self.id:
            return f"{self._page}/posts/{self.id.split('_')[-1]}"

        return f"{self._page}/photos/{self.id}"

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
        logger.info("Posting single image (published: %s)", self.published)

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

    def __repr__(self) -> str:
        return f"<Post {self._page} (published: {self.published})>"


class _PostMetadataModel(BaseModel):
    id: str
    impressions: int = 0
    other_clicks: int = 0
    photo_view: int = 0
    engaged_users: int = 0
    haha: int = 0
    like: int = 0
    love: int = 0
    sad: int = 0
    angry: int = 0
    wow: int = 0
    care: int = 0
    shares: int = 0
    comments: int = 0


_INSIGHT_METRICS = "post_impressions,post_clicks_by_type,post_engaged_users"
_REACTS = [
    "reactions.type(LIKE).limit(0).summary(true).as(like)",
    "reactions.type(LOVE).limit(0).summary(true).as(love)",
    "reactions.type(WOW).limit(0).summary(true).as(wow)",
    "reactions.type(HAHA).limit(0).summary(true).as(haha)",
    "reactions.type(SAD).limit(0).summary(true).as(sad)",
    "reactions.type(ANGRY).limit(0).summary(true).as(angry)",
    "reactions.type(CARE).limit(0).summary(true).as(care)",
]
_FIELDS = f"{','.join(_REACTS)},shares,comments.limit(0).summary(true)"


def check_insights_health(token):
    assert isinstance(
        get_post_metadata("406353451429614", GraphAPI(token)), _PostMetadataModel
    )


def get_post_metadata(post_id, api: GraphAPI):
    og_id = post_id

    if "_" not in post_id:
        logger.debug("Photo ID. Getting post ID")
        post_id = api.get(f"{post_id}?fields=page_story_id", retry=0)["page_story_id"]
        logger.debug("Post ID: %s", post_id)

    url = f"{post_id}/insights?metric={_INSIGHT_METRICS}"

    result = api.get(url, retry=0)
    item = {"id": og_id}

    for data_item in result["data"]:
        value = data_item["values"][0]["value"]
        if isinstance(value, dict):
            for k, v in value.items():
                item[k.replace(" ", "_")] = v
        else:
            item[data_item["name"].lstrip("post_")] = value

    result = api.get(f"{post_id}?fields={_FIELDS}", retry=0)

    for reaction in ("haha", "like", "love", "sad", "angry", "wow", "care"):
        item[reaction] = result[reaction]["summary"]["total_count"]

    try:
        item["shares"] = result["shares"]["count"]
    except KeyError:
        item["shares"] = 0

    try:
        item["comments"] = result["comments"]["summary"]["total_count"]
    except KeyError:
        item["comments"] = 0

    return _PostMetadataModel(**item)


def _dt_to_sql(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def register_metadata(pm: _PostMetadataModel):
    with sqlite3.connect(KINOBASE) as conn:
        conn.set_trace_callback(logger.debug)
        conn.execute(
            "update posts set shares=?,comments=?,impressions=?,other_clicks=?,photo_view=?"
            ",engaged_users=?,haha=?,like=?,love=?,sad=?,angry=?,wow=?,care=?,last_scan=? where id=?",
            (
                pm.shares,
                pm.comments,
                pm.impressions,
                pm.other_clicks,
                pm.photo_view,
                pm.engaged_users,
                pm.haha,
                pm.like,
                pm.love,
                pm.sad,
                pm.angry,
                pm.wow,
                pm.care,
                _dt_to_sql(datetime.datetime.now()),
                pm.id,
            ),
        )


def register_posts_metadata(
    token, from_=None, to_=None, ignore_non_zero_impressions=False
):
    from_ = _dt_to_sql(from_ or datetime.datetime(2019, 1, 1))
    if to_ is None:
        to_ = "now"
    else:
        to_ = _dt_to_sql(to_)

    posts = sql_to_dict(
        KINOBASE,
        "select * from posts where (added between date(?) and date(?))",
        (from_, to_),
    )
    logger.info("Posts to scan: %s", len(posts))

    api = GraphAPI(token)

    for post in posts:
        try:
            if ignore_non_zero_impressions and post["impressions"] > 0:
                logger.debug("Ignoring non-zero impressions: %s", post)
                continue

            logger.debug("Scanning post: %s", post)
            meta = get_post_metadata(post["id"], api)
        except FacepyError as error:
            logger.error(error)
            continue

        register_metadata(meta)
