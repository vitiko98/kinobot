#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import sqlite3
from typing import List, Sequence

from .constants import KINOBASE

logger = logging.getLogger(__name__)


class Kinobase:
    " Base class for Kinobot's database interaction. "

    __database__ = KINOBASE
    __insertables__ = ()

    table = "movies"

    def _execute_many(self, sql: str, seq_of_params: Sequence[tuple]):
        with sqlite3.connect(self.__database__) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.set_trace_callback(logger.debug)
            conn.executemany(sql, seq_of_params)

    def _fetch(self, sql: str, params: tuple) -> tuple:
        with sqlite3.connect(self.__database__) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.set_trace_callback(logger.debug)
            return conn.execute(sql, params).fetchone()

    def _execute_sql(self, sql: str, params: tuple):
        logger.debug("Database path: %s", self.__database__)
        with sqlite3.connect(self.__database__) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.set_trace_callback(logger.debug)
            conn.execute(sql, params)

    def _db_command_to_dict(
        self,
        sql: str,
        params: tuple = (),
    ) -> List[dict]:
        logger.debug("Database path: %s", self.__database__)
        return sql_to_dict(self.__database__, sql, params)

    def _insert(self):
        self._execute_sql(self._get_insert_command(), self._get_sqlite_tuple())

    def _update(self, id_):
        command = (
            f"update {self.table} set {'=?, '.join(self.__insertables__)}=? where id=?"
        )
        params = self._get_sqlite_tuple() + (id_,)
        self._execute_sql(command, params)

    def _get_insert_command(self) -> str:
        columns = ",".join(self.__insertables__)
        placeholders = ",".join("?" * len(self.__insertables__))
        gen = f"insert or ignore into {self.table} ({columns}) values ({placeholders})"
        logger.debug("Generated insert command: %s", gen)
        return gen

    def _get_sqlite_tuple(self) -> tuple:
        return tuple(getattr(self, attr) for attr in self.__insertables__)

    def _set_attrs_to_values(self, item: dict):
        for key, val in item.items():
            # logger.debug("%s: %s", key, val)
            if hasattr(self, key):
                setattr(self, key, val)


class Execute(Kinobase):
    " Class for predefined database tasks. "

    def reset_limits(self):
        " Reset role limits for users IDs. "
        self._execute_sql("update role_limits set hits=1", ())


def sql_to_dict(
    database: str,
    sql: str,
    params: tuple = (),
) -> List[dict]:
    """Convert a SQL query to a list of dictionaries.

    :param sql:
    :type sql: str
    :param params:
    :type params: tuple
    :rtype: List[dict]
    """
    database = database or KINOBASE
    with sqlite3.connect(database) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.set_trace_callback(logger.debug)
        conn.row_factory = sqlite3.Row

        conn_ = conn.cursor()
        conn_.execute(sql, params)

        fetched = conn_.fetchall()

        return [dict(row) for row in fetched]
