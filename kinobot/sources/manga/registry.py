# -*- coding: utf-8 -*-

import logging
import re
import sqlite3
from typing import List, Optional

from fuzzywuzzy import fuzz
import pydantic
import requests

from kinobot.constants import KINOBASE
from kinobot.constants import YAML_CONFIG
from kinobot.exceptions import KinoException, NothingFound
from kinobot.utils import get_yaml_config

logger = logging.getLogger(__name__)


class ChapterPage(pydantic.BaseModel):
    path: str
    base_url: str
    hash: str
    page_number: int

    @property
    def url(self):
        return f"{self.base_url}/data/{self.hash}/{self.path}"

    @classmethod
    def from_data(cls, data: dict):
        base_url = data["baseUrl"]
        hash = data["chapter"]["hash"]

        items = []

        for n, item in enumerate(data["chapter"]["data"], start=1):
            items.append(cls(base_url=base_url, hash=hash, path=item, page_number=n))

        return items


class Chapter(pydantic.BaseModel):
    id: str
    chapter: int
    pages: int
    title = ""
    total = 1
    version = 1
    chapter_pages: List[ChapterPage] = []
    manga_id: Optional[str] = None

    @classmethod
    def from_data(cls, item):
        return cls(**item, **item.get("attributes", {}))

    def fetch_chapter_pages(self, client):
        self.chapter_pages = client.get_chapter(self.id)


class Relationship(pydantic.BaseModel):
    id: str
    type: str
    name: str

    @classmethod
    def from_data(cls, data: dict):
        items = []
        for rel in data.get("relationships", []):
            if "attributes" not in rel:
                continue

            items.append(cls(**rel, **rel["attributes"]))

        return items


def _dict_to_title(item):
    language = list(item.keys())[0]
    title = item[language]
    return Title(language=language, title=title, main=item.get("main", False))


class Title(pydantic.BaseModel):
    language: str
    title: str
    main = True

    @classmethod
    def from_attributes(cls, attrs: dict):
        attrs["title"]["main"] = True

        items = [_dict_to_title(attrs["title"])]

        for alt_title in attrs["altTitles"]:
            items.append(_dict_to_title(alt_title))

        return items


class Manga(pydantic.BaseModel):
    id: str
    titles: List[Title]
    relationships: List[Relationship]
    chapters: List[Chapter] = []
    status = "unknown"
    original_language = "en"
    year: Optional[int] = None

    @classmethod
    def from_data(cls, data: List[dict]):
        items = []
        for item in data:
            titles = Title.from_attributes(item["attributes"])
            relationships = Relationship.from_data(item)
            item.pop("relationships")
            items.append(
                cls(
                    titles=titles,
                    relationships=relationships,
                    id=item["id"],
                    **item["attributes"],
                )
            )

        return items

    @property
    def url(self):
        return f"https://mangadex.org/title/{self.id}"

    @property
    def markdown_url(self):
        return f"[{self.pretty_title()}]({self.url})"

    @property
    def main_title(self):
        try:
            return [title for title in self.titles if title.main][0]
        except IndexError:
            raise NotImplementedError

    def fetch_chapters(self, client):
        self.chapters = client.feed_paginated(self.id)

    def pretty_title(self):
        title = self.main_title.title
        if self.year is not None:
            title = f"{title} ({self.year})"

        return title


_BASE_URL = "https://api.mangadex.org"


class Client:
    def __init__(self, session=None):
        self._session = session or requests.Session()

    @classmethod
    def from_config(cls, path=None):
        return cls()

    def search(self, title):
        response = self._session.get(
            f"{_BASE_URL}/manga?includes[]=author&includes[]=artist",
            params={"title": title},
        )
        response.raise_for_status()
        return Manga.from_data(response.json()["data"])

    def feed_paginated(self, id):
        items = []
        for offset in range(0, 2000, 99):
            new_items = self.feed(id, offset, limit=99)
            if not new_items:
                logger.debug("No more items to fetch")
                break

            items.extend(new_items)

        return items

    def chapter(self, id):
        response = self._session.get(f"{_BASE_URL}/chapter/{id}")

        if response.status_code == 404:
            raise NothingFound

        response.raise_for_status()

        try:
            data_ = response.json()["data"]
        except KeyError:
            raise MangaNotFound

        try:
            manga_id = [
                item["id"] for item in data_["relationships"] if item["type"] == "manga"
            ][0]
            data_["manga_id"] = manga_id
            return Chapter.from_data(data_)
        except (KeyError, IndexError):
            raise MangaNotFound("Error parsing chapter")

    def feed(self, id, offset=0, limit=99):
        params = {"translatedLanguage[]": ["en"], "offset": offset, "limit": limit}
        response = self._session.get(f"{_BASE_URL}/manga/{id}/feed", params=params)
        response.raise_for_status()

        r_json = response.json()

        items = []

        for item in r_json["data"]:
            try:
                item["total"] = r_json["total"]
                items.append(Chapter.from_data(item))
            except pydantic.ValidationError as error:
                logger.error(f"Error parsing {item}: {error}")

        return items

    def get_chapter_pages(self, id):
        response = self._session.get(f"{_BASE_URL}/at-home/server/{id}")
        response.raise_for_status()

        return ChapterPage.from_data(response.json())


class MangaRegistryException(KinoException):
    pass


class AlreadyAdded(MangaRegistryException):
    pass


class InvalidInput(MangaRegistryException):
    pass


class MangaNotFound(MangaRegistryException):
    pass


_CHAPTER_RE = re.compile(r"chapter\s(?P<x>[\d\S]+)", flags=re.IGNORECASE)
_PAGE_RE = re.compile(r"page\s(?P<x>\d+)", flags=re.IGNORECASE)
_ID_RE = re.compile(r"id:\s(?P<x>\d)", flags=re.IGNORECASE)


class MangaQuery(pydantic.BaseModel):
    title: Optional[str] = None
    id: Optional[str] = None
    chapter: Optional[str] = None
    page: Optional[int] = None

    @classmethod
    def from_str(cls, str_: str):
        try:
            id_ = _ID_RE.search(str_).group("x")
        except (AttributeError, IndexError):
            id_ = None

        try:
            chapter = _CHAPTER_RE.search(str_).group("x")
        except (AttributeError, IndexError):
            chapter = None

        try:
            page = _PAGE_RE.search(str_).group("x")
        except (AttributeError, IndexError):
            page = None

        title = str_
        for to_r in (_CHAPTER_RE, _PAGE_RE, _ID_RE):
            title = to_r.sub("", title).strip()

        return cls(title=title, id=id_, chapter=chapter, page=page)


class Repository:
    def __init__(self, db_path) -> None:
        self._db_path = db_path

    @classmethod
    def from_constants(cls):
        return cls(KINOBASE)

    def simple_search(self, query: str, limit=10):
        query = query.lower().strip()

        if not query:
            raise InvalidInput

        with sqlite3.connect(self._db_path) as conn:
            item_list = conn.execute(
                "select mangas.id from mangas where mangas.title like ? limit ?",
                (
                    f"%{query}%",
                    limit,
                ),
            ).fetchall()

            if not item_list:
                raise NothingFound

        return [self.from_manga_id(id[0]) for id in item_list]

    def search_manga(self, query: str):
        query = query.lower().strip()

        if not query:
            raise InvalidInput

        with sqlite3.connect(self._db_path) as conn:
            item_list = conn.execute(
                ('select (mangas.title || " " || mangas.year),mangas.id from mangas')
            ).fetchall()

        initial = 0
        final_list = []
        for item in item_list:
            if not item[0]:
                continue

            to_compare = item[0].lower().strip()
            if query == to_compare:
                logger.debug("Exact match found: %s", to_compare)
                return item[-1]

            fuzzy = fuzz.ratio(query, to_compare)

            if fuzzy > initial:
                initial = fuzzy
                final_list.append(item)

        if not final_list:
            raise MangaNotFound(query)

        item = final_list[-1]

        if initial < 59:
            logger.debug("Manga not found. Ratio is %s", initial)
            raise MangaNotFound(query)

        logger.debug("Manga %s found with %s ratio", item, initial)
        return item[-1]

    def get_chapters(self, manga_id, chapter_number):
        with sqlite3.connect(self._db_path) as conn:
            chapters = conn.execute(
                "select * from manga_chapters where manga_id=? and chapter=?",
                (
                    manga_id,
                    chapter_number,
                ),
            ).fetchall()
            chapters = [
                Chapter(id=c[0], chapter=c[-1], pages=c[3], title=c[2], version=c[4])
                for c in chapters
            ]
            if not chapters:
                raise MangaNotFound(
                    f"{chapter_number} not found for manga with {manga_id} ID"
                )

            return chapters

    def get_chapter(self, chapter_id):
        with sqlite3.connect(self._db_path) as conn:
            chapters = conn.execute(
                "select * from manga_chapters where id=?", (chapter_id,)
            ).fetchall()
            chapters = [
                Chapter(id=c[0], chapter=c[-1], pages=c[3], title=c[2], version=c[4])
                for c in chapters
            ]
            if not chapters:
                raise MangaNotFound(f"{chapter_id} not found")

            return chapters[0]

    def from_manga_id(self, id):
        with sqlite3.connect(self._db_path) as conn:
            manga = conn.execute("select * from mangas where id=?", (id,)).fetchone()
            if not manga:
                raise MangaNotFound(id)

            relationships = conn.execute(
                "select * from manga_relationships where manga_id=?", (id,)
            ).fetchall()
            relationships = [
                Relationship(id=r[0], type=r[2], name=r[3]) for r in relationships
            ]
            # chapters = conn.execute(
            #    "select * from manga_chapters where manga_id=?", (id,)
            # ).fetchall()
            # chapters = [
            #    Chapter(id=c[0], chapter=c[-1], pages=c[3], title=c[2], total=1)
            #    for c in chapters
            # ]

            return Manga(
                id=manga[0],
                titles=[Title(language="en", title=manga[1])],
                relationships=relationships,
                chapters=[],
                year=manga[2],
                original_language=manga[3],
                status=manga[4],
            )

    def add_manga(self, manga: Manga, register_relationships=False):
        with sqlite3.connect(self._db_path) as conn:
            conn.set_trace_callback(logger.debug)

            try:
                last_row = conn.execute(
                    "insert into mangas (id,title,year,original_language,status) values (?,?,?,?,?)",
                    (
                        manga.id,
                        manga.main_title.title,
                        manga.year,
                        manga.original_language,
                        manga.status,
                    ),
                ).lastrowid
                conn.commit()

                if register_relationships:
                    self.add_manga_relationships(manga.id, manga.relationships)
                    self.add_manga_chapters(manga.id, manga.chapters)

                return last_row
            except sqlite3.IntegrityError:
                raise AlreadyAdded(f"Manga with {manga.id} ID already added")

    def add_manga_relationships(self, manga_id, relationships: List[Relationship]):
        for relationship in relationships:
            with sqlite3.connect(self._db_path) as conn:
                conn.set_trace_callback(logger.debug)

                try:
                    conn.execute(
                        "insert into manga_relationships (id,manga_id,type,name) values (?,?,?,?)",
                        (
                            relationship.id,
                            manga_id,
                            relationship.type,
                            relationship.name,
                        ),
                    ).lastrowid

                    conn.commit()
                except sqlite3.IntegrityError:
                    conn.rollback()

    def add_manga_chapters(self, manga_id, chapters: List[Chapter]):
        for chapter in chapters:
            with sqlite3.connect(self._db_path) as conn:
                conn.set_trace_callback(logger.debug)
                try:
                    conn.execute(
                        "insert into manga_chapters (id,manga_id,title,pages,version,chapter) values (?,?,?,?,?,?)",
                        (
                            chapter.id,
                            manga_id,
                            chapter.title,
                            chapter.pages,
                            chapter.version,
                            chapter.chapter,
                        ),
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    conn.rollback()
