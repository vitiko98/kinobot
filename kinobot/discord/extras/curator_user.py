from abc import ABC
import datetime
import logging
import sqlite3
from typing import Optional

import pydantic

logger = logging.getLogger(__name__)

MIN_BYTES = None


class LogModel(pydantic.BaseModel):
    user_id: str
    size: int
    added: datetime.datetime
    note: Optional[str] = None


class Key(LogModel):
    user_id: str
    size: int
    added: datetime.datetime
    expires_in: datetime.timedelta = datetime.timedelta(days=90)
    note: Optional[str] = None


class CuratorABC(ABC):
    def __init__(self, user_id):
        self.user_id = user_id

    def is_curator(self):
        return False

    def keys(self):
        raise NotImplementedError

    def additions(self):
        raise NotImplementedError

    def can_add(self, size):
        raise NotImplementedError

    def size_left(self):
        raise NotImplementedError

    def register_addition(self, size, note=None):
        raise NotImplementedError

    def register_key(self, size, note=None):
        raise NotImplementedError


class CuratorTest(CuratorABC):
    def __init__(self, user_id, keys=None, additions=None):
        self.user_id = user_id
        self._keys = keys or []
        self._additions = additions or []

    def is_curator(self):
        return sum(self._keys) > 0

    def can_add(self, size):
        return self.size_left() > size

    def size_left(self):
        return sum(self._keys) - sum(self._additions)

    def register_addition(self, size, note=None):
        self._additions.append(size)

    def register_key(self, size, note=None):
        self._keys.append(size)


class Curator(CuratorABC):
    def __init__(self, user_id, db_path):
        self._conn = sqlite3.connect(db_path)
        self._conn.set_trace_callback(logger.debug)
        self.user_id = user_id

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._conn.close()

    def keys(self, include_expired=False):
        # select * from curator_keys where user_id = '291667438314192896' and datetime(added, '+' || 1000 || ' days') > datetime('now');
        if include_expired:
            result = self._conn.execute(
                "select * from curator_keys where user_id=?", (self.user_id,)
            ).fetchall()
        else:
            result = self._conn.execute(
                "select * from curator_keys where user_id = ? and datetime(added, '+' || days_expires_in || ' days') >= datetime('now')",
                (self.user_id,),
            )
        return [
            Key(
                user_id=self.user_id,
                size=item[1],
                added=item[2],
                note=item[3],
                expires_in=datetime.timedelta(days=item[4]),
            )
            for item in result
        ]

    def lifetime_used_bytes(self):
        result = self._conn.execute(
            (
                "select coalesce((select sum(size) from curator_additions where user_id=?), 0) from curator_keys where user_id=?"
            ),
            (
                self.user_id,
                self.user_id,
            ),
        ).fetchone()
        if result:
            return result[0] or 0

        return 0

    def expired_bytes_no_use(self):
        result = self._conn.execute(
            (
                "select sum(size) - coalesce((select sum(size) from curator_additions where user_id=? AND "
                "added < datetime('now', '-' || days_expires_in || ' days')), 0) from curator_keys where user_id=? "
                "and datetime(added, '+' || days_expires_in || ' days') < datetime('now')"
            ),
            (
                self.user_id,
                self.user_id,
            ),
        ).fetchone()
        if result:
            return result[0] or 0

        return 0

    def additions(self):
        result = self._conn.execute(
            "select * from curator_additions where user_id=?", (self.user_id,)
        ).fetchall()
        return [
            LogModel(
                user_id=self.user_id,
                size=item[1],
                added=item[2],
                note=item[3],
            )
            for item in result
        ]

    def size_left(self):
        result = self._conn.execute(
            (
                "select sum(size) - coalesce((select sum(size) from curator_additions where user_id=? AND added "
                ">= datetime('now', '-' || days_expires_in || ' days')), 0) from curator_keys where user_id=? "
                "and datetime(added, '+' || days_expires_in || ' days') >= datetime('now')"
            ),
            (
                self.user_id,
                self.user_id,
            ),
        ).fetchone()
        if result:
            return result[0] or 0

        return 0

    def can_add(self, size):
        return self.size_left() > size

    def close(self):
        self._conn.close()

    def register_addition(self, size, note=None):
        self._conn.execute(
            "insert into curator_additions (user_id,size,note) values (?,?,?)",
            (self.user_id, size, note),
        )
        self._conn.commit()

    def register_key(self, size, note=None, expires_in=datetime.timedelta(days=90)):
        self._conn.execute(
            "insert into curator_keys (user_id,size,note,days_expires_in) values (?,?,?,?)",
            (self.user_id, size, note, expires_in.days),
        )
        self._conn.commit()
