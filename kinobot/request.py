#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import datetime
import logging
import re

from random import randint
from typing import List, Optional, Sequence, Tuple, Union

import timeago

from .db import Kinobase, sql_to_dict
from .exceptions import InvalidRequest, NothingFound
from .frame import GIF, Static, Swap
from .item import RequestItem
from .media import ExternalMedia, LocalMedia, hints
from .user import User
from .utils import clean_url_for_fb, get_args_and_clean

_REQUEST_RE = re.compile(r"[^[]*\[([^]]*)\]")
_MENTIONS_RE = re.compile(r"@([^\s]+)")
_EXTRA_MESSAGE_RE = re.compile(r"\:[^\]]*\:")
_ALL_BRACKET_RE = re.compile(r"\[[^\]]*\]")


logger = logging.getLogger(__name__)


class Request(Kinobase):
    "Base class for Kinobot requests."

    table = "requests"
    language_code = "en"
    _verification_table = "request_verifications"

    __handler__ = Static
    __gif__ = False
    __role_limit__ = "regular"
    __flags_tuple__ = (
        "--raw",
        "--ultraraw",
        "--font",
        "--font-color",
        "--font-size",
        "--text-spacing",
        "--text-align",
        "--y-offset",
        "--stroke-width",
        "--stroke-color",
        "--aspect-quotient",
        "--color",
        "--contrast",
        "--brightness",
        "--sharpness",
        "--no-collage",
        "--dimensions",
        "--glitch",
        "--apply-to",
        "--border",
        "--border-color",
        "--text-background",
    )
    __insertables__ = (
        "id",
        "user_id",
        "comment",
        "type",
        "used",
        "verified",
        "music",
        "language",
    )

    def __init__(
        self,
        comment: str,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        id: Optional[str] = None,
        type=None,
        **kwargs,
    ):
        """
        :param content:
        :type content: str
        :param user:
        :type user: Optional[User]
        :param id:
        :type id: Optional[str]
        """
        self.items: List[RequestItem] = []
        self.user = User(id=user_id, name=user_name)
        self.language = "en"  # Legacy. Useless now
        self.music = False
        self.verified = False
        self.used = False
        self._edited = False
        self._in_db = False
        self._handler: Optional[Union[Static, Swap]] = None

        self._set_attrs_to_values(kwargs)

        try:
            self.added = datetime.datetime.strptime(
                kwargs["added"], "%Y-%m-%d %H:%M:%S"
            )
        except KeyError:
            self.added = datetime.datetime.now()

        self.time_ago = timeago.format(self.added)

        self.comment = comment.strip()
        self.args = {}
        self.id = id or str(randint(100000, 200000))

        if type is None and self.comment.startswith("!"):
            type = self.comment.split(" ")[0].strip()

        self.type = (type or "!req").strip()

        if not self.type.startswith("!"):
            self.type = f"!{self.type}"

    @property
    def no_prefix(self):
        return self.comment.replace(self.type, "").lstrip()

    @property
    def title(self) -> str:
        return f"**{self.user.name}** - {self.comment}"

    @property
    def pretty_title(self) -> str:
        """
        >>> self.pretty_title
        >>> "!req ITEMS"

        :rtype: str
        """
        if self.comment.startswith(self.type):
            title = self.comment
        else:
            title = f"{self.type} {self.comment}"

        if "--image-url" in title:
            return clean_url_for_fb(title)

        return title

    @property
    def facebook_pretty_title(self) -> str:
        """The title used on Facebook posts.

        >>> cls.facebook_pretty_title
        >>> "Requested by someone (!req ITEMS)"

        :rtype: str
        """
        self._load_user()
        return f"Requested by {self.user.name} ({self.pretty_title}) ({self.time_ago})"

    @property
    def on_demand(self) -> bool:
        return not self._in_db

    @property
    def user_id(self) -> str:  # For insert command
        return self.user.id

    def register(self):
        "Register the request and the user if needed."
        if not self._in_db:
            self.user.register()
            self._insert()
            self._in_db = True

    def register_verifications(self, user_ids, verified: bool, reason=None):
        if self._verification_table is None:
            return None

        self._execute_many(
            f"insert into {self._verification_table} (user_id,request_id,reason,verified) values (?,?,?,?)",
            [(user_id, self.id, reason, verified) for user_id in user_ids],
        )

    def get_verifications(self):
        if self._verification_table is None:
            return []

        result = self._sql_to_dict(
            f"select * from {self._verification_table} where request_id=?", (self.id,)
        )
        if not result:
            return []

        return result

    def get_handler(self, user: Optional[User] = None) -> Union[Static, Swap]:
        """Return an Static or a GIF handler. The user instance is optional for
        role limit checks; if used, it must have its role attribute loaded.

        :param user:
        :type user: Optional[User]
        :rtype: Union[Static, GIF]
        """
        # Temporary
        if self.type == "!swap":
            self.__handler__ = Swap

        checkable = self.on_demand and user is not None

        if checkable:
            self.user = user
            self.user.check_role_limit(self.__role_limit__)

        clean = self.comment.strip()
        for cleaner in _ALL_BRACKET_RE, _EXTRA_MESSAGE_RE:
            clean = cleaner.sub("", clean).strip()

        logger.debug("Clean text to process: %s", clean)

        try:
            self.args = get_args_and_clean(clean, self.__flags_tuple__)[-1]
            self._load_media_requests()
            self._handler = self.__handler__.from_request(self)
        except Exception:
            if checkable and self.user.unlimited is False:
                self.user.substract_role_limit()
            raise

        return self._handler  # Temporary

    def verify(self):
        self.verified = True
        self._update_db("verified")

    def append_text(self, text: str, prefix="edited"):
        self.comment = (
            f"{self.comment.strip()} ::{prefix.strip().upper()}:: {text.strip()}"
        )
        self._update(self.id)
        self._edited = True
        logger.debug("Updated comment: %s", self.comment)

    def reset_append(self, prefix="edited"):
        prefix_str = f"::{prefix.strip().upper()}::"
        logger.debug("About to reset append: %s", self.comment)
        self.comment = self.comment.split(prefix_str)[0].strip()
        self._update(self.id)
        logger.debug("Append reset: %s", self.comment)

    @property
    def edited(self):
        return self._edited

    def mark_as_used(self):
        self.used = True
        self._update_db("used")

    def delete(self):
        self.mark_as_used()

    def find_dupe(self, offset="-3 month", verified=True):
        sql = (
            "SELECT * from requests where comment like ? and "
            "added > date('now', ?) and id != ? and verified = ?"
        )
        params = (self.no_prefix, offset, self.id, verified)
        result = sql_to_dict(self.__database__, sql, params)
        if result:
            return self.from_sqlite_dict(result[0])

        return None

    def register_ice(self):
        self._execute_sql(
            "insert into request_ices (request_id) values (?)", (self.id,)
        )

    def get_ices(self):
        items = (
            self._sql_to_dict(
                "select * from request_ices where request_id=? order by added asc",
                (self.id,),
            )
            or []
        )
        # Too late to use sqlite3.PARSE_DECLTYPES
        for item in items:
            item["added"] = datetime.datetime.strptime(
                item["added"], "%Y-%m-%d %H:%M:%S"
            )
            item["ago"] = item["added"] - datetime.datetime.now()

        return items

    @classmethod
    def from_fb(cls, comment: dict, identifier="en"):
        """Parse a request from a Facebook comment dictionary.

        :param comment:
        :type comment: dict
        """
        req_cls = _req_cls_map.get(identifier, cls)
        user = comment.get("from", {})
        return req_cls(
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
        req = sql_to_dict(
            cls.__database__, f"select * from {cls.table} where id=?", (id_,)
        )
        if not req:
            raise NothingFound("Request not found by `{id_}` ID")

        req = req[0]
        req["comment"] = f"{req['type'].lower()} {req['comment']}"  # Legacy

        return cls(**req, _in_db=True)

    @classmethod
    def random_from_queue(cls, verified: bool = False):
        """Pick a random request from the database.

        :param verified:
        :type verified: bool
        :raises exceptions.NothingFound
        """
        req = sql_to_dict(
            cls.__database__,
            f"select * from {cls.table} where used=0 and verified=? order by RANDOM() limit 1",
            (verified,),
        )
        if not req:
            raise NothingFound(f"No random request found (verified: {verified})")

        return cls.from_sqlite_dict(req[0])

    @classmethod
    def from_sqlite_dict(cls, item: dict):
        return cls(**item, _in_db=True)

    @classmethod
    def from_discord(cls, args: Sequence[str], ctx, identifier="en", prefix="!req"):
        "Parse a request from a discord.commands.Context object."
        req_cls = _req_cls_map.get(identifier, cls)
        return req_cls(
            " ".join(args), ctx.author.id, ctx.author.name, ctx.message.id, type=prefix
        )

    @classmethod
    def from_tweepy(cls, status):
        "Parse a request from a tweepy.Status object."
        tweet = _MENTIONS_RE.sub("", status.text).strip()
        return cls(tweet, status.user.id, status.user.name, status.id)

    def _load_media_requests(self):
        self.items = []

        for item in self._get_media_requests():
            logger.debug("Loading item tuple: %s", item)
            self.items.append(
                RequestItem(item[0], item[1], self.__gif__, self.language_code)
            )

    def _get_item_tuple(self, item: str) -> Tuple[hints, Sequence[str]]:
        title = item.split("[")[0].replace(self.type, "").strip()
        if len(title) < 4:
            raise InvalidRequest(f"Expected title with more than 3 chars: {item}")

        content = _REQUEST_RE.findall(item)
        if not content:
            raise InvalidRequest(f"No content brackets found: {item}")

        logger.debug("Title to search: %s", title)
        media = ExternalMedia.from_request(title)
        if media is None:
            media = LocalMedia.from_request(title)
        else:
            title = title.replace(f"!{media.type}", "").strip()

        return media.from_query(title), content

    def _get_media_requests(
        self,
    ) -> Sequence[Tuple[Union[hints], Sequence[str]]]:
        """Return a RequestItem-parseable sequence of tuples.

        >>> req.get_media()
        >>> [("Movie", ["Quote", "Minute"])]

        :rtype: Sequence[Tuple[Union[Movie, Episode, Song], Sequence[str]]]
        """
        if self.type in ("!parallel", "!swap"):
            split_content = self.comment.split("|")

            if len(split_content) < 2:
                raise InvalidRequest("Invalid parallel request: expected => 2 items")

            return [self._get_item_tuple(tuple_) for tuple_ in split_content]

        return [self._get_item_tuple(self.comment)]

    def _update_db(self, column: str, value=1):
        self._execute_sql(
            f"update {self.table} set {column}=? where id=?", (value, self.id)
        )

    def _load_user(self):
        if self.user.name is None or self.user.name == "Anonymous":
            self.user.load()

    def __repr__(self):
        return f"<Request: {self.comment} ({self.language_code})>"


class RequestMain(Request):
    _verification_table = None

    table = "requests_main"


class RequestEs(Request):
    _verification_table = None

    table = "requests_es"
    language_code = "es"

    @property
    def facebook_pretty_title(self) -> str:
        self._load_user()
        return f"Pedido por {self.user.name} ({self.pretty_title})"


class RequestPt(Request):
    _verification_table = None

    table = "requests_pt"
    language_code = "pt"

    @property
    def facebook_pretty_title(self) -> str:
        self._load_user()
        return f"Pedido por {self.user.name} ({self.pretty_title})"


_req_cls_map = {"es": RequestEs, "pt": RequestPt, "main": RequestMain}


def get_cls(identifier):
    return _req_cls_map.get(identifier, Request)


class ClassicRequest(Request):
    """Classic request.

    Syntax example:
        `!req ITEM [BRACKET_CONTENT]...`
    """

    discord_help = {
        "help": f"A normal request\n\nHelp: https://kino.caretas.club/docs/core.html#req",
        "usage": "ITEM",
    }


class ParallelRequest(Request):
    """Parallel request.

    Syntax example:
        `!palette ITEM [BRACKET_CONTENT] | ITEM_ [BRACKET_CONTENT]...`
    """

    type = "!parallel"
    discord_help = {
        "help": f"A parallel request\n\nHelp: https://kino.caretas.club/docs/core.html#parallel",
        "usage": "ITEM | ITEM...",
    }


class GifRequest(Request):
    """GIF request.

    Syntax example:
        `!gif ITEM [TIMESTAMP - TIMESTAMP]`
        `!gif ITEM [BRACKET_CONTENT]...`
    """

    type = "!gif"
    __handler__ = GIF
    __gif__ = True
    __role_limit__ = "gif"


class PaletteRequest(Request):
    """Palette request.

    Syntax example:
        `!palette ITEM [BRACKET_CONTENT]`

    Supported platforms:
        * Facebook
        * Discord
        * Twitter
    """

    type = "!palette"
    discord_help = {
        "help": f"A palette request\n\nHelp: https://kino.caretas.club/docs/core.html#palette",
        "usage": "ITEM",
    }


class SwapRequest(Request):
    """Swap request.

    Syntax example:
        `!swap SOURCE_ITEM [BRACKET_CONTENT] | ITEM [BRACKET_CONTENT]`

    Supported platforms:
        * Facebook
        * Discord
        * Twitter
    """

    __handler__ = Swap
    type = "!swap"
    discord_help = {
        "help": f"A swap request\n\nHelp: https://kino.caretas.club/docs/core.html#swap",
        "usage": "SOURCE_ITEM | DEST_ITEM",
    }


def get_media_item(item: str, type):
    title = item.split("[")[0].replace(type, "").strip()
    if len(title) < 4:
        raise InvalidRequest(f"Expected title with more than 3 chars: {item}")

    content = _REQUEST_RE.findall(item)
    if not content:
        raise InvalidRequest(f"No content brackets found: {item}")

    logger.debug("Title to search: %s", title)
    media = ExternalMedia.from_request(title)
    if media is None:
        media = LocalMedia.from_request(title)
    else:
        title = title.replace(f"!{media.type}", "").strip()

    return media.from_query(title)
