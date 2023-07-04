# -*- coding: utf-8 -*-

import datetime
import logging
import re
import sqlite3
from typing import List, Optional

from fuzzywuzzy import fuzz
import pydantic
import requests

from kinobot.constants import KINOBASE
from kinobot.constants import YAML_CONFIG
from kinobot.exceptions import KinoException
from kinobot.utils import get_yaml_config

logger = logging.getLogger(__name__)


CUTSCENE_URI_RE = re.compile(r"cutscene://(\S+):(\d+)")


class Cutscene(pydantic.BaseModel):
    uri: str
    name: str
    game_id: Optional[int] = None
    id: Optional[int] = None

    @property
    def markdown_url(self):
        return f"[{self.name}]({self.uri})"

    @property
    def uri_query(self):
        return f"cutscene://{self.game_id}:{self.id}"


class Company(pydantic.BaseModel):
    id: int
    name: str
    url: Optional[str] = None


class Game(pydantic.BaseModel):
    id: int
    url: str
    name: str
    franchises: List[int] = []
    involved_companies: List[int] = []
    first_release_date: Optional[datetime.datetime] = None
    company_objects: List[Company] = []
    cutscenes: List[Cutscene] = []

    def fetch_companies(self, client):
        self.company_objects = client.companies_from_involved(
            f'({",".join(str(id_) for id_ in self.involved_companies)})'
        )

    def pretty_title(self):
        if self.first_release_date:
            return f"{self.name} ({self.first_release_date.year})"

        return f"{self.name}"


class DbTrack(pydantic.BaseModel):
    artist: str
    name: str
    uri: str
    id: Optional[int] = None

    def pretty_title(self):
        return f"{self.artist} - {self.name}"


class Client:
    def __init__(self, client_id, client_secret, access_token, session=None) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = access_token
        self._session = session or requests.Session()

        self._session.headers.update(
            {
                "Client-ID": self._client_id,
                "Authorization": f"Bearer {self._access_token}",
            }
        )

    @classmethod
    def from_config(cls, path=None):
        return cls(**get_yaml_config(path or YAML_CONFIG, key="igdb"))  # type: ignore

    def auth(self):
        response = self._session.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
        )
        return response.json()

    def search(self, query):
        data = f'fields *;search "{query}"; limit 10;'

        # response = self._session.post("https://api.igdb.com/v4/search", data=data)
        response = self._session.post("https://api.igdb.com/v4/games", data=data)
        response.raise_for_status()
        items = []
        for item in response.json():
            try:
                items.append(Game(**item))
            except pydantic.ValidationError as error:
                logger.error(error)

        return items

    def companies_from_involved(self, ids):
        data = f"fields *; where id = {ids};"
        response = self._session.post(
            "https://api.igdb.com/v4/involved_companies", data=data
        )
        response.raise_for_status()
        companies = []
        for involved in response.json():
            try:
                data_ = f"fields *; where id = {involved['company']};"
            except KeyError:
                continue

            c_response = self._session.post(
                "https://api.igdb.com/v4/companies", data=data_
            )
            c_response.raise_for_status()
            companies.extend([Company(**item) for item in c_response.json()])

        return companies

    @classmethod
    def from_constants(cls):
        raise NotImplementedError

    def search_game(self):
        pass


class GamesRegistryException(KinoException):
    pass


class AlreadyAdded(GamesRegistryException):
    pass


class InvalidInput(GamesRegistryException):
    pass


class GameNotFound(GamesRegistryException):
    pass


class Repository:
    def __init__(self, db_path) -> None:
        self._db_path = db_path

    @classmethod
    def from_constants(cls):
        return cls(KINOBASE)

    def simple_search(self, query: str, limit=5, fetch=True):
        if not query:
            raise InvalidInput

        with sqlite3.connect(self._db_path) as conn:
            conn.set_trace_callback(logger.info)
            item_list = conn.execute(
                (
                    'select games.id from games where (games.name || " " || SUBSTRING(games.first_release_date, '
                    '1, INSTR(games.first_release_date, "-") - 1)) like (?) limit ?'
                ),
                (
                    f"%{query}%",
                    limit,
                ),
            ).fetchall()

        games = []
        if item_list:
            for id in item_list:
                if fetch:
                    games.append(self.from_game_id(id[0]))

        return games or item_list

    def from_uri_query(self, query: str):
        match = CUTSCENE_URI_RE.match(query)
        if match is None:
            raise InvalidInput("Invalid uri query. Use cutscene://GAME_ID:CUTSCENE_ID")

        game_id, c_id = match.group(1), match.group(2)

        with sqlite3.connect(self._db_path) as conn:
            item = conn.execute(
                "select * from game_cutscenes where game_id=? and id=?", (game_id, c_id)
            ).fetchone()
            if not item:
                raise GameNotFound(query)

            return Cutscene(uri=item[3], name=item[2], game_id=item[1], id=item[0])

    def search_cutscene(self, query: str) -> Cutscene:
        query = query.lower().strip()

        if not query:
            raise InvalidInput

        try:
            return self.from_uri_query(query)
        except InvalidInput:
            pass

        with sqlite3.connect(self._db_path) as conn:
            item_list = conn.execute(
                (
                    'select (games.name || " " || SUBSTRING(games.first_release_date, 1, '
                    'INSTR(games.first_release_date, "-") - 1) || " " || game_cutscenes.name), game_cutscenes.* '
                    "from games left join game_cutscenes on games.id=game_cutscenes.game_id;"
                )
            ).fetchall()

        initial = 0
        final_list = []
        for item in item_list:
            if not item[0]:
                continue

            to_compare = item[0].lower().strip()
            if query == to_compare:
                logger.debug("Exact match found: %s", to_compare)
                return Cutscene(uri=item[4], name=item[3], game_id=item[2], id=item[1])

            fuzzy = fuzz.ratio(query, to_compare)

            if fuzzy > initial:
                initial = fuzzy
                final_list.append(item)

        if not final_list:
            raise GameNotFound(query)

        item = final_list[-1]

        if initial < 59:
            logger.debug("Song not found. Ratio is %s", initial)
            raise GameNotFound(query)

        logger.debug("Cutscene %s found with %s ratio", item, initial)
        return Cutscene(uri=item[4], name=item[3], game_id=item[2], id=item[1])

    def from_game_id(self, id):
        with sqlite3.connect(self._db_path) as conn:
            conn.set_trace_callback(logger.debug)
            result = conn.execute("select * from games where id=?", (id,)).fetchone()
            if not result:
                raise GameNotFound(id)

            companies = conn.execute(
                "select id,name,url from game_companies where game_id=?", (id,)
            ).fetchall()
            companies = [Company(id=c[0], name=c[1], url=c[2]) for c in companies]
            cutscenes = conn.execute(
                "select id,name,uri from game_cutscenes where game_id=?", (id,)
            ).fetchall()
            cutscenes = [
                Cutscene(id=c[0], name=c[1], uri=c[2], game_id=id) for c in cutscenes
            ]

            game = Game(
                id=result[0],
                url=result[1],
                name=result[2],
                first_release_date=result[3],
                company_objects=companies,
                cutscenes=cutscenes,
            )

            return game

    def add_game(self, game, with_companies=True):
        with sqlite3.connect(self._db_path) as conn:
            conn.set_trace_callback(logger.debug)

            try:
                last_row = conn.execute(
                    "insert into games (id,url,name,first_release_date) values (?,?,?,?)",
                    (game.id, game.url, game.name, game.first_release_date),
                ).lastrowid
                conn.commit()
                if with_companies:
                    self.add_companies(game)

                return last_row
            except sqlite3.IntegrityError as error:
                raise AlreadyAdded(f"Game with {game.id} ID already added")

    def add_cutscene(self, cutscene):
        with sqlite3.connect(self._db_path) as conn:
            conn.set_trace_callback(logger.debug)

            try:
                last_row = conn.execute(
                    "insert into game_cutscenes (game_id,name,uri) values (?,?,?)",
                    (cutscene.game_id, cutscene.name, cutscene.uri),
                ).lastrowid

                conn.commit()

                return Cutscene(
                    uri=cutscene.uri,
                    name=cutscene.name,
                    game_id=cutscene.game_id,
                    id=last_row,
                )
            except sqlite3.IntegrityError as error:
                raise AlreadyAdded(f"Cutscene already added: {error}")

    def delete_cutscene(self, id):
        with sqlite3.connect(self._db_path) as conn:
            conn.set_trace_callback(logger.debug)

            conn.execute(
                "delete from game_cutscenes where id=?",
                (id,),
            )
            conn.commit()

    def add_companies(self, game):
        for company in game.company_objects:
            with sqlite3.connect(self._db_path) as conn:
                conn.set_trace_callback(logger.debug)
            try:
                conn.execute(
                    "insert into game_companies (id,game_id,name,url) values (?,?,?,?)",
                    (company.id, game.id, company.name, company.url),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
