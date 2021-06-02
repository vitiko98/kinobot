#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import sqlite3
from typing import List

import requests

from .cache import PATREON_MEMBERS_TIME, region
from .constants import (
    PATREON_ACCESS_TOKEN,
    PATREON_API_BASE,
    PATREON_CAMPAIGN_ID,
    PATREON_TIER_IDS,
)
from .db import Kinobase, sql_to_dict
from .exceptions import InvalidRequest, LimitExceeded, NothingFound

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
        self._registered = False

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

    def get_badges_2(self) -> List[dict]:
        """Get a list of won badges by the user.

        :rtype: List[dict] (keys: 'badge_id' and 'count')
        :raises exceptions.NothingFound
        """
        sql = (
            "select badge_id, count(*) count from user_badges where"
            " user_id=? group by badge_id order by count desc"
        )
        badges = self._db_command_to_dict(sql, (self.id,))
        if not badges:
            raise NothingFound

        return badges

    def get_badges(self):  # Implement later
        sql = (
            "select badges.*, count(*) as count, sum(badges.weight) as total "
            "from user_badges left join badges on user_badges.badge_id="
            "badges.id where user_id=? group by user_badges.badge_id;"
        )
        badges = self._db_command_to_dict(sql, (self.id,))
        if not badges:
            raise NothingFound

        return badges

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
        logger.info("User roles %s", self.roles)
        logger.info("Key roles %s", key_roles)
        matches = sum([role in key_roles for role in self.roles])

        if matches:
            logger.debug("User has unlimited requests for %s requests", request_key)
        else:
            logger.info("Matches found: %s", matches)
            self._handle_role_limit(5 if request_key != "gif" else 1)

    def _handle_role_limit(self, limit: int = 5):
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

            logger.info(f"Hits: {hits}")
            if not hits:
                raise LimitExceeded()

            conn.execute(
                "update role_limits set hits=hits+1 where user_id=?", (self.id,)
            )
            conn.commit()

    def substract_role_limit(self):
        self._execute_sql(
            "update role_limits set hits=hits-1 where user_id=?", (self.id,)
        )

    def _is_patron(self) -> bool:
        """Check if the user is an active Patron by ID. Load roles if found."

        :rtype: bool
        """
        responses = _get_patreon_members("cache")
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
