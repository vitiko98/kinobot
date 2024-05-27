#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import datetime
import logging
import sqlite3
from typing import List

import requests

from .cache import PATREON_MEMBERS_TIME
from .cache import region
from .constants import LANGUAGE_SUFFIXES
from .constants import PATREON_ACCESS_TOKEN
from .constants import PATREON_API_BASE
from .constants import PATREON_CAMPAIGN_ID
from .constants import PATREON_TIER_IDS
from .db import Kinobase
from .db import sql_to_dict
from .exceptions import InvalidRequest
from .exceptions import LimitExceeded
from .exceptions import NothingFound

logger = logging.getLogger(__name__)

_REQ_DICT = {
    "gif": ["auteur", "botmin"],
    "regular": ["director", "auteur", "botmin"],
}

_RATING_DICT = {
    0.5: '"Peak Cringe"',
    1.0: '"Peak Cringe"',
    1.5: '"Certified Cringe"',
    2.0: '"Certified Cringe"',
    2.5: '"Borderline Cringe"',
    3.0: '"Borderline Kino"',
    3.5: '"Certified Kino"',
    4.0: '"High Kino"',
    4.5: '"High Kino"',
    5.0: '"Peak Kino"',
}


class User(Kinobase):
    table = "users"

    def __init__(self, **kwargs):
        self.id = "0000"  # Anonymous
        self.name = "Anonymous"
        self.role = "Unknown"
        self.points = 0
        self.position = 0
        self.language = "en"
        self._registered = False
        self._remain = 0

        self._set_attrs_to_values(kwargs)

    @classmethod
    def from_fb(cls, name: str, id: str):
        return cls(name=name, id=id)

    @classmethod
    def from_discord(cls, ctx_author):
        role = ",".join([str(role.name) for role in ctx_author.roles])
        return cls(name=ctx_author.display_name, id=ctx_author.id, role=role)

    @classmethod
    def from_twitter(cls, user):
        return cls(name=user.screen_name, id=user.id)

    @classmethod
    def from_id(cls, id_: str):
        sql = "select * from users where id=? limit 1"
        result = sql_to_dict(cls.__database__, sql, (id_,))
        if not result:
            raise NothingFound

        return cls(**result[0], _registered=True)

    @classmethod
    def from_query(cls, query: str):
        sql = "select * from users where name like ? limit 1"
        result = sql_to_dict(cls.__database__, sql, (f"%{query}%",))

        if not result:
            raise NothingFound

        return cls(**result[0], _registered=True)

    @property
    def roles(self) -> list:
        if self.role is not None:
            return self.role.split(",")

        return []

    @property
    def top_title(self) -> str:
        return f"**{self.position}**. *{self.name}* (**{self.points} points**)"

    @property
    def unlimited(self):
        return self._remain == -1

    def load_language(self):
        result = self._db_command_to_dict(
            "select language from user_languages where user_id=?", (self.id,)
        )
        if result:
            self.language = result[0]["language"]
            logger.debug("Loaded user language: %s", self.language)
        else:
            logger.debug("User language not found in database")
            self._execute_sql(
                "insert into user_languages (user_id) values (?)", (self.id,)
            )

    def update_language(self, language: str = "en"):
        if language not in LANGUAGE_SUFFIXES:
            raise InvalidRequest(f"Invalid language: {language}")

        self.load_language()
        self._execute_sql(
            "update user_languages set language=? where user_id=?",
            (
                language,
                self.id,
            ),
        )
        self.language = language

    def get_queued_requests(self, used: int = 0) -> List[dict]:
        results = self._db_command_to_dict(
            "select * from requests where user_id=? and used=?",
            (
                self.id,
                used,
            ),
        )
        if not results:
            raise NothingFound

        return results

    def posts_stats_count(self, column: str):
        columns = (
            "shares",
            "comments",
            "impressions",
            "other_clicks",
            "photo_view",
            "engaged_users",
            "haha",
            "like",
            "love",
            "sad",
            "angry",
            "wow",
            "care",
        )
        if column not in columns:
            raise InvalidRequest(f"Choose between: {', '.join(columns)}")

        result = self._sql_to_dict(
            f"select sum(posts.{column}) as stats_count from posts "
            "inner join requests on posts.request_id=requests.id "
            "where requests.user_id=?",
            (self.id,),
        )
        if not result:
            return 0

        return result[0]["stats_count"] or 0

    def purge(self):
        self._execute_sql("update requests set used=1 where user_id=?", (self.id,))

    def rate_media(self, media, rating: float):
        if not _RATING_DICT.get(float(rating)):
            raise InvalidRequest("Invalid rating: choose between 0.5 to 5")

        table = media.type + "_ratings"
        try:
            self._execute_sql(
                f"insert into {table} (rated_{media.type}, rated_by, rating) values (?,?,?)",
                (
                    media.id,
                    self.id,
                    rating,
                ),
            )
        except sqlite3.IntegrityError:
            self._execute_sql(
                f"update {table} set rating=? where rated_by=? and "
                f"rated_{media.type}=?",
                (
                    rating,
                    self.id,
                    media.id,
                ),
            )

    def register(self):
        try:
            self._execute_sql(
                "insert into users (id, name, role) values (?,?,?)",
                (
                    self.id,
                    self.name,
                    ",".join(self.roles),
                ),
            )
        except sqlite3.IntegrityError:
            logger.info("Already registered")

        self._registered = True

    def load(self, register: bool = True):
        result = self._db_command_to_dict(
            "select * from users where id=?",
            (self.id,),
        )
        if not result and register:
            logger.debug("User not found")
            self.register()
        else:
            self._set_attrs_to_values(result[0])

    def update_name(self, name: str):
        self._execute_sql(
            "update users set name=? where id=?",
            (
                name,
                self.id,
            ),
        )

    def update_role(self, role: str):
        """
        :param role: patreon or discord role
        """
        self._execute_sql(
            "update users set role=? where id=? and name=?",
            (role, self.id, self.name),
        )
        self.role = role

    def check_role_limit(self, request_key: str = "regular"):
        """
        :param request_key:
        :type request_key: str
        :raises LimitExceeded
        """
        key_roles = _REQ_DICT[request_key]
        logger.info("User roles -> key roles: %s -> %s", self.roles, key_roles)
        matches = sum([role in key_roles for role in self.roles])

        if matches:
            logger.debug("User has unlimited requests for %s requests", request_key)
            self._remain = -1
        else:
            logger.info("Matches found: %s", matches)
            self._handle_role_limit(7 if request_key != "gif" else 1)

    def get_balance(self):
        received = self._sql_to_dict(
            "select sum(amount) - (select sum(amount) from transactions where from_id=?) from transactions where to_id=?",
            (self.id,),
        )

    def pay(self, user_id, note):
        pass

    @property
    def remain_requests(self) -> str:
        if self.unlimited:
            return "This user has unlimited requests."

        return f"This user has {self._remain} daily requests left."

    def _handle_role_limit(self, limit: int = 7):
        with sqlite3.connect(self.__database__) as conn:
            conn.set_trace_callback(logger.debug)
            try:
                conn.execute(
                    "insert into role_limits (user_id) values (?)",
                    (self.id,),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                pass

            hits = conn.execute(
                "select hits from role_limits where user_id=? and hits <= ?",
                (
                    self.id,
                    limit,
                ),
            ).fetchone()

            if not hits:
                raise LimitExceeded

            conn.execute(
                "update role_limits set hits=hits+1 where user_id=?", (self.id,)
            )
            conn.commit()
            self._remain = limit - int(hits[0])

    def substract_role_limit(self):
        if self._remain != -1:
            self._execute_sql(
                "update role_limits set hits=hits-1 where user_id=?", (self.id,)
            )

    def _is_patron(self) -> bool:
        """Check if the user is an active Patron by ID. Load roles if found."

        :rtype: bool
        """
        # Temporary
        inc = 0
        while True:
            inc += 1
            try:
                responses = _get_patreon_members("cache")
                break
            except requests.RequestException:
                if inc > 5:
                    raise NotImplementedError

        for response in responses:
            data = response.get("data", [])
            included = response.get("included", [])[: len(data)]
            if self._check_discord_user(data, included):
                return True

        return False

    def _check_discord_user(self, data, included) -> bool:
        for item, included in zip(data, included):
            try:
                tiers = item["relationships"]["currently_entitled_tiers"]["data"]
                tier_id = [tier["id"] for tier in tiers if tier["type"] == "tier"][0]
                # patreon_id = item["relationships"]["user"]["data"]["id"]
            except (IndexError, KeyError):
                continue

            discord = included["attributes"]["social_connections"]["discord"]

            if discord is not None and str(discord["user_id"]) == str(self.id):
                self.role = PATREON_TIER_IDS.get(tier_id)
                logger.debug("Patron found: %s", self.role)
                return True

        return False

    def __repr__(self):
        return f"<User {self.name} ({self.roles})>"


class ForeignUser(User):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        assert self._is_patron() is not None

    @classmethod
    def from_discord(cls, ctx_author):
        return cls(name=ctx_author.display_name, id=ctx_author.id)


@region.cache_on_arguments(expiration_time=PATREON_MEMBERS_TIME)
def _get_patreon_members(cache: str):
    assert cache is not None
    headers = {
        "Authorization": f"Bearer {PATREON_ACCESS_TOKEN}",
        "User-Agent": "Kinobot",
    }
    client = requests.Session()
    client.headers.update(headers)
    url = (
        f"{PATREON_API_BASE}/campaigns/{PATREON_CAMPAIGN_ID}/members?"
        "include=currently_entitled_tiers,user&fields[user]=social_connections"
    )

    results = []
    while True:
        response = client.get(url)
        response.raise_for_status()
        response = response.json()
        results.append(response)
        next_ = response.get("links", {}).get("next")
        if next_ is None:
            break

        url = next_

    return results


def get_top_raw(
    db: str,
    column: str,
    offset=0,
    limit=100,
    from_=None,
    to_=None,
    order="desc",
    min_posts=None,
):
    mean_sql = (
        "with unique_users as (select count(posts.id) from posts "
        "inner join requests on posts.request_id=requests.id group "
        "by requests.user_id) select (select count(id) * 1.0 from posts)"
        "/ count(*) * 1.0 from unique_users;"
    )

    with sqlite3.connect(db) as conn:
        conn.set_trace_callback(logger.debug)

        mean = float(conn.execute(mean_sql).fetchone()[0])
        min_posts = (
            mean if min_posts is None else min_posts
        )  # or operator will ignore 0
        logger.debug("Posts mean: %s", mean)

        sql = (
            f"select avg(posts.{column})as rating, "
            "count(posts.id) as posts_count, users.name as user_name, users.id as user_id "
            "from posts inner join requests on posts.request_id=requests.id inner join users "
            "on requests.user_id=users.id where posts.added between date(?) and date(?) "
            "group by requests.user_id having "
            f"count(posts.id) >= {min_posts} order by rating "
            f"{order} limit {limit} offset {offset};"
        )
        items = (
            sql_to_dict(
                db, sql, (from_ or str(datetime.datetime(2020, 1, 1)), to_ or "now")
            )
            or []
        )
        for n, item in enumerate(items, 1):
            item["position"] = n

        return items


def get_top(
    db: str,
    column: str,
    offset=0,
    limit=100,
    from_=None,
    to_=None,
    order="desc",
    min_posts=None,
):
    mean_sql = (
        "with unique_users as (select count(posts.id) from posts "
        "inner join requests on posts.request_id=requests.id group "
        "by requests.user_id) select (select count(id) * 1.0 from posts)"
        "/ count(*) * 1.0 from unique_users;"
    )

    with sqlite3.connect(db) as conn:
        conn.set_trace_callback(logger.debug)

        mean = float(conn.execute(mean_sql).fetchone()[0])
        min_posts = (
            mean if min_posts is None else min_posts
        )  # or operator will ignore 0
        logger.debug("Posts mean: %s", mean)

        sql = (
            f"select ((count(posts.id) * 1.0) / ((count(posts.id)*1.0) + {mean})) "
            f"* avg(posts.{column}) + ({mean} / ((count(posts.id) * 1.0) + {mean})) "
            f"* (select avg(posts.{column}) from posts) as rating, "
            "count(posts.id) as posts_count, users.name as user_name, users.id as user_id "
            "from posts inner join requests on posts.request_id=requests.id inner join users "
            "on requests.user_id=users.id where posts.added between date(?) and date(?) and impressions>0 "
            "group by requests.user_id having "
            f"count(posts.id) >= {min_posts} order by rating "
            f"{order} limit {limit} offset {offset};"
        )
        items = (
            sql_to_dict(
                db, sql, (from_ or str(datetime.datetime(2020, 1, 1)), to_ or "now")
            )
            or []
        )
        for n, item in enumerate(items, 1):
            item["position"] = n

        return items


def get_top_position(db, user_id, column, from_=None, to_=None, min_posts=None):
    user_id = str(user_id)

    top = get_top(db, column, from_=from_, to_=to_, min_posts=min_posts, limit=-1) or []
    top_len = len(top)
    try:
        position = [user for user in top if user["user_id"] == user_id][0]
        position["top_len"] = top_len
        return position
    except IndexError:
        return None
