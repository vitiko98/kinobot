from hashlib import md5
import os
import re
import tempfile
import time
from typing import List, Optional

from pydantic import BaseModel
import requests

from kinobot.constants import YAML_CONFIG
from kinobot.utils import get_yaml_config

_CHAPTER_RE = re.compile(r"(chapter|issue)\s(?P<x>[\d\S]+)", flags=re.IGNORECASE)
_PAGE_RE = re.compile(r"page\s(?P<x>\d+)", flags=re.IGNORECASE)
_ID_RE = re.compile(r"id:\s?(?P<x>\d+)", flags=re.IGNORECASE)


class ComicQuery(BaseModel):
    title: Optional[str] = None
    id: Optional[str] = None
    chapter: Optional[int] = None
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

        return cls(title=title, id=id_, chapter=chapter, page=page)  # type: ignore


def _to_camel(string: str) -> str:
    result = "".join(word.capitalize() for word in string.split("_"))
    return result[0].lower() + result[1:]


class IdName(BaseModel):
    id: int
    name: str


class SeriesMetadata(BaseModel):
    id: int
    writers: List[IdName] = []
    publishers: List[IdName] = []
    editors: List[IdName] = []
    colorists: List[IdName] = []
    language: str = "en"
    release_year: str

    class Config:
        alias_generator = _to_camel


class Chapter(BaseModel):
    id: int
    number: str = ""
    title = ""
    pages: int
    title_name = ""

    class Config:
        alias_generator = _to_camel


class Series(BaseModel):
    id: int
    name: str
    metadata: Optional[SeriesMetadata] = None
    chapters: List[Chapter] = []


def _get_cache(cache_file):
    if os.path.isfile(cache_file):
        file_mtime = os.path.getmtime(cache_file)
        time_diff = time.time() - file_mtime
        if time_diff <= 3 * 24 * 60 * 60:
            with open(cache_file, "r") as f:
                token = f.read().strip()
                return token


class Client:
    def __init__(
        self, url, api_key, username, password, session=None, **kwargs
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._session = session or requests.Session()
        headers = {
            "Accept": "application/json",
        }
        self._session.headers.update(headers)
        self.login(username, password)

    @classmethod
    def from_config(cls, path=None):
        return cls(**get_yaml_config(path or YAML_CONFIG, "comics"))

    def login(self, username, password):
        id = md5((self._url + self._api_key + username + password).encode()).hexdigest()
        cache_file = os.path.join(tempfile.gettempdir(), f"{id}.cache")

        cached = _get_cache(cache_file)
        if cached:
            self._session.headers.update({"Authorization": f"Bearer {cached}"})
            return None

        response = self._session.post(
            f"{self._url}/api/Account/login",
            json={"username": username, "password": password},
        )
        response.raise_for_status()
        token = response.json()["token"]
        self._session.headers.update({"Authorization": f"Bearer {token}"})

        with open(cache_file, "w") as f:
            f.write(token)

        return None

    def search(self, query):
        params = {
            "queryString": query,
        }
        response = self._session.get(f"{self._url}/api/search/search", params=params)
        response.raise_for_status()
        return [
            Series(id=item["seriesId"], name=item["name"])
            for item in response.json()["series"]
        ]

    def series_metadata(self, id):
        params = {
            "seriesId": id,
        }

        response = self._session.get(f"{self._url}/api/series/metadata", params=params)
        response.raise_for_status()
        return SeriesMetadata(**response.json())

    def series_chapters(self, id):
        params = {
            "seriesId": id,
        }

        response = self._session.get(
            f"{self._url}/api/series/series-detail", params=params
        )
        response.raise_for_status()

        return [Chapter(**item) for item in response.json()["chapters"]]

    def image_url(self, chapter_id, page):
        return f"{self._url}/api/reader/image?chapterId={chapter_id}&apiKey={self._api_key}&page={page}"

    def first_series_matching(self, query):
        result = self.search(query)
        if not result:
            return None

        item = result[0]
        item.metadata = self.series_metadata(item.id)
        item.chapters = self.series_chapters(item.id)

        return item

    def scan_all(self):
        response = self._session.get(f"{self._url}/api/Library")
        response.raise_for_status()
        ids = [item["id"] for item in response.json()]
        for id in ids:
            response = self._session.post(
                "https://kvt.caretas.club/api/library/scan", params={"libraryId": id}
            )
            response.raise_for_status()

    def series(self, id):
        response = self._session.get(f"{self._url}/api/series/{id}")
        response.raise_for_status()
        return Series(**response.json())

    def get_series(self, id):
        item = self.series(id)
        item.metadata = self.series_metadata(item.id)
        item.chapters = self.series_chapters(item.id)

        return item
