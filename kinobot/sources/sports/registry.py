# -*- coding: utf-8 -*-

import datetime
import logging
import re
from typing import List

from fuzzywuzzy import fuzz
import pydantic
from pydantic import ConfigDict
from sqlalchemy import Column
from sqlalchemy import create_engine
from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.exc import IntegrityError as _IntegrityError
from sqlalchemy.orm import column_property
from sqlalchemy.orm import sessionmaker

from kinobot.sources import Base
from kinobot.sources import config

logger = logging.getLogger(__name__)


URI_RE = re.compile(r"sports://(\d+)")


class IntegrityError(Exception):
    pass


class SportsMatchDB(Base):
    __tablename__ = "sports_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tournament = Column(String)
    title = Column(String)
    uri = Column(String, unique=True)
    added = Column(DateTime, default=datetime.datetime.utcnow)
    complete_title = column_property(title + " - " + tournament)


class SportsMatch(pydantic.BaseModel):
    id: int
    tournament: str
    title: str
    uri: str
    model_config = ConfigDict(from_attributes=True)

    @property
    def id_uri(self):
        return f"sports://{self.id}"

    @property
    def markdown_url(self):
        return f"[{self.pretty_title}]({self.uri})"

    @property
    def pretty_title(self):
        return f"{self.title} - {self.tournament} [{self.id_uri} !sports]"


def _detect_uri(query: str):
    match = URI_RE.match(query)
    if match is None:
        return None

    return match.group(1)


def fuzzy_search(query: str, items: List[str], ratio=59):
    if not query:
        return None

    initial = 0
    final_list = []
    for n, item in enumerate(items):
        if not item:
            continue

        to_compare = item.lower().strip()
        if query == to_compare:
            logger.debug("Exact match found: %s", to_compare)
            return n

        fuzzy = fuzz.ratio(query, to_compare)

        if fuzzy > initial:
            initial = fuzzy
            final_list.append(n)

    if not final_list:
        return None

    item = final_list[-1]

    if initial < ratio:
        logger.debug("Item not found. Ratio is %s", initial)
        return None

    logger.debug("'%s' found with %s ratio", query, initial)
    return item


def make_engine(url=None):
    engine = create_engine(url or config.sources.sqlalchemy_url)
    return engine


class Repository:
    def __init__(self, db_session):
        self._db_session = db_session

    def close(self):
        self._db_session.close()

    @classmethod
    def from_db_url(cls, url=None, engine=None):
        if engine is None:
            engine = make_engine(url)

        Session = sessionmaker(bind=engine)()
        return cls(Session)

    def create(self, tournament, title, uri):
        new_match = SportsMatchDB(tournament=tournament, title=title, uri=uri)

        try:
            self._db_session.add(new_match)
            self._db_session.commit()
        except _IntegrityError:
            raise IntegrityError

        return SportsMatch.from_orm(new_match)

    def get_by_id(self, id):
        match = self._db_session.query(SportsMatchDB).filter_by(id=id).first()
        if match:
            return SportsMatch.from_orm(match)
        return None

    def get_by_uri(self, uri):
        match = self._db_session.query(SportsMatchDB).filter_by(uri=uri).first()
        if match:
            return SportsMatch.from_orm(match)
        return None

    def delete(self, id):
        item = self.get_by_id(id)
        if item is None:
            return None

        self._db_session.delete(item)
        self._db_session.commit()

    def fuzzy_search(self, query):
        id = _detect_uri(query)
        if id:
            logger.debug("ID detected")
            return self.get_by_id(id)

        items = self._db_session.query(SportsMatchDB).all()
        titles = [result.complete_title for result in items]
        match = fuzzy_search(query, titles)
        if match is None:
            return None

        return SportsMatch.from_orm(items[match])

    def partial_search(self, query):
        search_term = f"%{query}%"
        query = (
            self._db_session.query(SportsMatchDB)
            .filter(SportsMatchDB.complete_title.ilike(search_term))
            .all()
        )
        return [SportsMatch.from_orm(item) for item in query]
