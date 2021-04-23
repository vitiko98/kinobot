#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import re
from random import randint
from typing import List, Optional, Sequence, Tuple, Union

from .db import Kinobase, sql_to_dict
from .exceptions import InvalidRequest, NothingFound
from .frame import GIF, Static
from .item import RequestItem
from .media import Episode, Movie, Song
from .user import User
from .utils import get_args_and_clean, is_episode

_REQUEST_RE = re.compile(r"[^[]*\[([^]]*)\]")
_MENTIONS_RE = re.compile(r"@([^\s]+)")


logger = logging.getLogger(__name__)


class Request(Kinobase):
    """
    Represent a Request object able to take requests from sqlite,
    Facebook, Twitter, Discord, and arbitrary strings.
    """

    type = "!req"
    table = "requests"
    _handler = Static
    _gif = False
    _role_limit = "regular"
    _flags_tuple = (
        "--raw",
        "--font",
        "--aspect-quotient",
        "--contrast",
        "--brightness",
        "--sharpness",
    )
    __insertables__ = (
        "id",
        "user_id",
        "comment",
        "type",
        "used",
        "verified",
        "music",
    )

    def __init__(
        self,
        comment: str,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        id: Optional[str] = None,
        **kwargs,
    ):
        """
        :param content:
        :type content: str
        :param user:
        :type user: Optional[User]
        :param id:
        :type id: Optional[str]
        :raises exceptions.InvalidRequest
        """
        self.items: List[RequestItem] = []
        self.user_id = user_id or "n/a"
        self.user_name = user_name
        self.music = False
        self.on_demand = False
        self.verified = False
        self.priority = False
        self.used = False
        self._in_db = False

        self._set_attrs_to_values(kwargs)

        self.comment = comment.strip()
        self.args = {}
        self.id = id or str(randint(100000, 200000))

    @property
    def title(self) -> str:
        return f"**{self.user_id}** - {self.comment}"

    @property
    def user(self) -> User:
        return User(id=self.user_id, name=self.user_name)

    @property
    def pretty_title(self) -> str:
        if self.comment.startswith(self.type):
            return self.comment

        return f"{self.type} {self.comment}"

    def register(self):
        if not self._in_db:
            self.user.register()
            self._insert()

    def get_handler(self, user: Optional[User] = None) -> Static:
        """Return an Static or a GIF handler. The user is optional and only
        used to check role limits for on-demand requests.

        :param user:
        :type user: Optional[User]
        :rtype: Union[Static, GIF]
        """
        if self.on_demand and user:
            user.check_role_limit(self._role_limit)

        self.args = get_args_and_clean(self.comment, self._flags_tuple)[-1]

        self._load_media_requests()

        return self._handler.from_request(self)

    def insert_to_database(self):
        assert not self._in_db, "Request is already in the database"
        self._insert()
        self._in_db = True

    def verify(self):
        self.verified = True
        self._update_db("verified")

    def mark_as_used(self):
        self.used = True
        self._update_db("used")

    def delete(self):
        self.mark_as_used()

    @classmethod
    def from_fb(cls, comment: dict):
        user = comment.get("from", {})
        return cls(
            comment.get("message", "n/a"),
            user.get("id"),
            user.get("name"),
            comment.get("id"),
            music=comment.get("music", False),
        )

    @classmethod
    def from_db_id(cls, id_: str):
        """Return a Request object from ID if found.

        :param id_:
        :type id_: str
        :raises exceptions.NothingFound
        """
        req = sql_to_dict(cls.__database__, "select * from requests where id=?", (id_,))
        if not req:
            raise NothingFound("Request not found by `{id_}` ID")

        req = req[0]
        req["comment"] = f"{req['type'].lower()} {req['comment']}"  # Legacy

        return cls(**req, _in_db=True)

    @classmethod
    def random_from_queue(cls, verified: bool = False):
        req = sql_to_dict(
            cls.__database__,
            "select * from requests where used=0 and verified=? order by RANDOM() limit 1",
            (verified,),
        )
        if not req:
            raise NothingFound(f"No random request found (verified: {verified})")

        return cls(**req[0], _in_db=True)

    @classmethod
    def from_sqlite_dict(cls, item: dict):
        return cls(**item, _in_db=True)

    @classmethod
    def from_discord(cls, args: Sequence[str], ctx, on_demand: bool = True):
        return cls(
            " ".join(args),
            ctx.author.id,
            ctx.author.name,
            ctx.message.id,
            on_demand=on_demand,
        )

    @classmethod
    def from_tweepy(cls, status):
        tweet = _MENTIONS_RE.sub("", status.text).strip()
        return cls(tweet, status.user.id, status.user.name, status.id)

    def _load_media_requests(self):

        for item in self._get_media_requests():
            logger.debug("Loading item tuple: %s", item)
            self.items.append(RequestItem(item[0], item[1], self._gif))

    def _get_item_tuple(
        self, item: str
    ) -> Tuple[Union[Movie, Episode, Song], Sequence[str]]:
        title = item.split("[")[0].strip()
        if len(title) < 4:
            raise InvalidRequest(f"Expected title with more than 3 chars: {item}")

        content = _REQUEST_RE.findall(item)
        if not content:
            raise InvalidRequest(f"No content brackets found: {item}")

        if len(content) > 1 and self.type == "!parallel":
            raise InvalidRequest("Parallel item must take only one content bracket")

        media = Episode if is_episode(title) else Song if self.music else Movie

        return (
            media.from_query(title.replace(self.type, "")),
            content,
        )

    def _get_media_requests(
        self,
    ) -> Sequence[Tuple[Union[Movie, Episode, Song], Sequence[str]]]:
        """Return a RequestItem-parseable sequence of tuples.

        >>> req.get_media()
        >>> [("Movie", ["Quote", "Minute"])]

        :rtype: Sequence[Tuple[Union[Movie, Episode, Song], Sequence[str]]]
        """
        if self.type == "!parallel":
            split_content = self.comment.split("|")

            if len(split_content) < 2:
                raise InvalidRequest("Invalid parallel request: expected => 2 items")

            return [self._get_item_tuple(tuple_) for tuple_ in split_content]

        return [self._get_item_tuple(self.comment)]

    def _update_db(self, column: str, value=1):
        self._execute_sql(
            f"update requests set {column}=? where id=?", (value, self.id)
        )

    def __repr__(self):
        return f"<Request: {self.comment}>"


class ClassicRequest(Request):
    """Classic request.

    Syntax example:
        `!req ITEM [BRACKET_CONTENT]...`

    Notes:
        * The square bracket limit is 8. This can vary if the requested quotes
        are short.
        * Timestamp brackets support extra milliseconds (e.g. [01:02:03.400]).
        * Quote brackets support extra milliseconds (e.g. [Quote ++100],
        [Quote 2 --300]).
        * There's index support for quoted requests (e.g. [0-2, 3]). (Note that
        index requests don't support milliseconds).
        * Mixed requests (timestamps and quotes) are supported.

    Supported platforms:
        * Facebook
        * Discord
        * Twitter
    """


class ParallelRequest(Request):
    """Parallel request.

    Syntax example:
        `!palette ITEM [BRACKET_CONTENT] | ITEM_ [BRACKET_CONTENT]...`

    Notes:
        * The item* limit is 4.
        * The bracket limit per item is 1. You can, however, request the same item* twice.
        * Timestamp brackets support extra milliseconds (e.g. [01:02:03.400]).
        * Quote brackets support extra milliseconds (e.g. [Quote ++100],
        [Quote 2 --300]).
        * There's index support for quoted requests (e.g. [0-2, 3]). (Note that
        index requests don't support milliseconds).
        * Mixed requests (timestamps and quotes) are supported.

        *item: Movie or Episode.

    Supported platforms:
        * Facebook
        * Discord
        * Twitter
    """

    type = "!parallel"


class GifRequest(Request):
    """GIF request.

    Syntax example:
        `!gif ITEM [TIMESTAMP - TIMESTAMP]`
        `!gif ITEM [BRACKET_CONTENT]...`

    Notes:
        * The square bracket limit for quotes is 4. This can vary if the
        requested quotes are short.
        * The range limit is 7 seconds.
        * Quote brackets support extra milliseconds (e.g. [Quote ++100],
        [Quote 2 --300]).
        * There's index support for quoted requests (e.g. [0-2, 3]). (Note that
        index requests don't support milliseconds).
        * Movies and Episodes are supported.
        * Mixed requests (timestamps and quotes) are supported.
        * This is the most resource intensive request available.

    Supported platforms:
        * Discord
        * Twitter
    """

    type = "!gif"
    _handler = GIF
    _gif = True
    _role_limit = "gif"


class PaletteRequest(Request):
    """Palette request.

    Syntax example:
        `!palette ITEM [BRACKET_CONTENT]`

    Notes:
        * The square bracket limit is 1.
        * Movies and Episodes are supported.
        * Timestamp values also support milliseconds (e.g. [01:02:03.400]).
        * Quote requests are supported, but the quote will be removed from the
        final frame.
        * There's index support for quoted requests (e.g. [0-2, 3]). (Note that
        index requests don't support milliseconds).

    Supported platforms:
        * Facebook
        * Discord
        * Twitter
    """

    type = "!palette"
