# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

from typing import List

import datetime
import logging
import sqlite3
import numpy
import pydantic

from kinobot.exceptions import NothingFound


logger = logging.getLogger(__name__)


class UserBasic(pydantic.BaseModel):
    position: int
    id: str
    name: str
    rating: float
    level: str

    def __str__(self) -> str:
        return f"{self.position:02}. {self.name} (rating: {self.rating})"


class VerifierTop(pydantic.BaseModel):
    users: List[UserBasic]
    column: str
    users_count: int
    from_: datetime.datetime
    to_: datetime.datetime

    def as_table(self):
        string = f"Verifiers top by {self.column} (from {self.from_} to {self.to_})"
        users_str = "\n".join(str(user) for user in self.users)
        return f"{string}\n\n{users_str}"


class PosterTop(VerifierTop):
    min_posts: int

    def as_table(self, limit=25):
        string = f"Posters top by {self.column} (from {self.from_} to {self.to_})\n(min posts to qualify: {self.min_posts})"
        users_str = "\n".join(str(user) for user in self.users[:limit])
        return f"{string}\n\n{users_str}"


_LEVELS = ("expert", "competent", "beginner")


def _get_levels(users):
    sliced = numpy.array_split(users, len(_LEVELS))
    levels = {}
    index = 0
    for user_list, level in zip(sliced, _LEVELS):
        for _ in user_list:
            levels[index] = level
            index += 1

    return levels


def _dt_to_sql(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _get_between(between):
    from_ = _dt_to_sql(between[0] or datetime.datetime(2019, 1, 1))
    if between[1] is None:
        to_ = "now"
    else:
        to_ = _dt_to_sql(between[1])

    return from_, to_


class Verifier:
    def __init__(self, user_id, db_path):
        self._conn = sqlite3.connect(db_path)
        self._conn.set_trace_callback(logger.debug)
        self.user_id = str(user_id)

    def get_top(self, column="impressions", between=(None, None)):
        between = _get_between(between)
        sql = (
            f"select avg(posts.{column}) as rating, count(posts.id) "
            "as posts_count, users.name as user_name, users.id as user_id from posts "
            "inner join requests on posts.request_id=requests.id inner join "
            "request_verifications on requests.user_id=request_verifications.user_id "
            "inner join users on request_verifications.user_id=users.id where "
            "(posts.added between date(?) and date(?)) group by request_verifications.user_id "
            "order by rating desc"
        )
        result = self._conn.execute(sql, between).fetchall()
        levels = _get_levels(result)

        users = []
        for num, item in enumerate(result, start=1):
            users.append(
                UserBasic(
                    position=num,
                    rating=item[0],
                    name=item[2],
                    id=item[3],
                    level=levels[num - 1],
                )
            )

        return VerifierTop(
            users=users,
            column=column,
            users_count=len(users),
            from_=between[0],
            to_=between[1],
        )

    def get_top_card(self, column="impressions", between=(None, None)) -> UserBasic:
        top = self.get_top(column, between)
        users = top.users
        try:
            return [user for user in users if user.id == self.user_id][0]
        except IndexError:
            raise NothingFound("User ID not found in verifiers")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._conn.close()

    def close(self):
        self._conn.close()


class Poster:
    def __init__(self, user_id, db_path):
        self._conn = sqlite3.connect(db_path)
        self._conn.set_trace_callback(logger.debug)
        self.user_id = str(user_id)

    def get_top(self, column="impressions", between=(None, None), min_posts=7):
        between = _get_between(between)
        sql = (
            f"select avg(posts.{column}) as rating, count(posts.id) "
            "as posts_count, users.name as user_name, users.id as user_id from posts "
            "inner join requests on posts.request_id=requests.id "
            "inner join users on requests.user_id=users.id where "
            "(posts.added between date(?) and date(?)) group by requests.user_id having "
            f"count(posts.id) >= {min_posts} order by rating desc"
        )
        result = self._conn.execute(sql, between).fetchall()
        levels = _get_levels(result)

        users = []
        for num, item in enumerate(result, start=1):
            users.append(
                UserBasic(
                    position=num,
                    rating=item[0],
                    name=item[2],
                    id=item[3],
                    level=levels[num - 1],
                )
            )

        return PosterTop(
            users=users,
            column=column,
            users_count=len(users),
            from_=between[0],
            to_=between[1],
            min_posts=min_posts,
        )

    def get_top_card(
        self, column="impressions", between=(None, None), min_posts=7
    ) -> UserBasic:
        top = self.get_top(column, between, min_posts)
        users = top.users
        try:
            return [user for user in users if user.id == self.user_id][0]
        except IndexError:
            raise NothingFound(
                f"User not found in top. Requirements are at least {min_posts} posts between {between}"
            )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._conn.close()

    def close(self):
        self._conn.close()
