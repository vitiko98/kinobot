#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import sqlite3
from typing import List

from .db import Kinobase
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
    def __init__(self, **kwargs):
        self.id = "0000"  # Anonymous
        self.name = "Anonymous"
        self.role = "Unknown"
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

    @property
    def roles(self) -> list:  # Legacy
        return self.role.split(",")

    def get_queued_requests(self, used: int = 0) -> List[dict]:
        results = self._db_command_to_dict(
            "select * from requests where id=? and used=?",
            (
                self.name,
                used,
            ),
        )
        if not results:
            raise NothingFound

        return results

    def get_badges_count(self) -> int:
        # sql = "select badge_id, count(badge_id) from user_badges where user_id=? group by badge_id"
        sql = "select count() from user_badges where user_id=? limit 1"
        badges = self._db_command_to_dict(sql, (self.id,))
        if not badges:
            return 0

        return badges[0]["count()"]

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
                f"update {table} set rating=? where rated_by=?",
                (
                    rating,
                    self.id,
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
            self._handle_role_limit(3 if request_key != "gif" else 1)

    def _handle_role_limit(self, limit: int = 3):
        with sqlite3.connect(self._database) as conn:
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
                raise LimitExceeded

            conn.execute(
                "update role_limits set hits=hits+1 where user_id=?", (self.id,)
            )
            conn.commit()
