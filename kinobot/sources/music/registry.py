# -*- coding: utf-8 -*-

import logging
import re
import sqlite3
from typing import List, Optional

from fuzzywuzzy import fuzz
import pydantic
import requests

from kinobot.constants import KINOBASE
from kinobot.exceptions import KinoException
from kinobot.constants import LAST_FM_KEY

logger = logging.getLogger(__name__)

_BASE_URL = "https://ws.audioscrobbler.com/2.0"  # ?method=track.search&track=Believe&api_key=YOUR_API_KEY&format=json
_GARBAGE_RE = re.compile(r"\((.*)| - (.*)")


class SearchTrack(pydantic.BaseModel):
    artist: str
    name: str
    url: str

    def pretty_title(self):
        return f"{self.artist} - {self.name}"


class DbTrack(pydantic.BaseModel):
    artist: str
    name: str
    uri: str
    id: Optional[int] = None

    def pretty_title(self):
        return f"{self.artist} - {self.name}"


class Client:
    def __init__(self, api_key, session=None) -> None:
        self._session = session or requests.Session()
        self._api_key = api_key

    @classmethod
    def from_constants(cls):
        return cls(LAST_FM_KEY)

    def search_track(self, track, artist=None, page=1, limit=10) -> List[SearchTrack]:
        params = {
            "method": "track.search",
            "track": track,
            "artist": artist,
            "page": page,
            "limit": limit,
            "format": "json",
            "api_key": self._api_key,
        }
        response = self._session.get(f"{_BASE_URL}/", params=params)
        response.raise_for_status()
        return [
            SearchTrack(**item)
            for item in response.json()["results"]["trackmatches"]["track"]
        ]


class MusicRegistryException(KinoException):
    pass


class AlreadyAdded(MusicRegistryException):
    pass


class InvalidInput(MusicRegistryException):
    pass


class SongNotFound(MusicRegistryException):
    pass


class Repository:
    def __init__(self, db_path) -> None:
        self._db_path = db_path

    @classmethod
    def from_constants(cls):
        return cls(KINOBASE)

    def simple_search(self, query: str, limit=20):
        if not query:
            raise InvalidInput

        with sqlite3.connect(self._db_path) as conn:
            conn.set_trace_callback(logger.info)
            item_list = conn.execute(
                'select * from music_songs where (artist || " " || title) like (?) limit ?',
                (
                    f"%{query}%",
                    limit,
                ),
            ).fetchall()

        if item_list:
            return [
                DbTrack(id=item[0], artist=item[1], name=item[2], uri=item[3])
                for item in item_list
            ]

        return []

    def search(self, query: str):
        query = query.lower().strip()

        if not query:
            raise InvalidInput

        with sqlite3.connect(self._db_path) as conn:
            item_list = conn.execute(
                'select *, (artist || " - " || title) from music_songs'
            ).fetchall()

        initial = 0
        final_list = []
        for item in item_list:
            to_compare = item[-1].lower().strip()
            if query == to_compare:
                logger.debug("Exact match found: %s", to_compare)
                return DbTrack(id=item[0], artist=item[1], name=item[2], uri=item[3])

            fuzzy = fuzz.ratio(query, to_compare)

            if fuzzy > initial:
                initial = fuzzy
                final_list.append(item)

        if not final_list:
            raise SongNotFound(query)

        item = final_list[-1]

        if initial < 59:
            logger.debug("Song not found. Ratio is %s", initial)
            raise SongNotFound(query)

        return DbTrack(id=item[0], artist=item[1], name=item[2], uri=item[3])

    def add(self, track):
        with sqlite3.connect(self._db_path) as conn:
            conn.set_trace_callback(logger.debug)

            try:
                return conn.execute(
                    "insert into music_songs (artist,title,uri) values (?,?,?)",
                    (track.artist, track.name, track.uri),
                ).lastrowid
            except sqlite3.IntegrityError as error:
                raise AlreadyAdded(error)
