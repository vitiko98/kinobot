import logging
import os
from typing import Optional

import pydantic
import requests
from discord import Embed

from kinobot.constants import RADARR_TOKEN, RADARR_URL
from kinobot.db import Kinobase
from kinobot.exceptions import KinoException

logger = logging.getLogger(__name__)


def _to_camel(string: str) -> str:
    result = "".join(word.capitalize() for word in string.split("_"))
    return result[0].lower() + result[1:]


class _RadarrMovieModel(pydantic.BaseModel):
    added: str
    title: str
    folder: str
    tmdb_id: int
    has_file: bool
    overview: str
    year: int
    imdb_id: Optional[str] = None
    remote_poster: Optional[str] = None
    original_title: Optional[str] = None

    class Config:
        alias_generator = _to_camel


class MovieView:
    _IMDB_BASE = "https://www.imdb.com/title"

    def __init__(self, data: dict):
        self._model = _RadarrMovieModel(**data)

    def pretty_title(self):
        if (
            self._model.original_title is None
            or self._model.title.lower() == self._model.original_title.lower()
        ):
            title = self._model.title
        else:
            title = f"{self._model.original_title} [{self._model.title}]"

        title = f"{title} ({self._model.year})"

        if self.already_added():
            title = f"{title} (Available on Kinobot)"

        if self.to_be_added():
            title = f"{title} (To be added)"

        return title

    def already_added(self):
        return self._model.has_file

    def to_be_added(self):
        return not self._model.has_file and self._model.added != "0001-01-01T00:00:00Z"

    def embed(self) -> Embed:
        """Discord embed used for Discord searchs.

        :rtype: Embed
        """
        embed = Embed(
            title=self.pretty_title(),
            url=self._imdb_url(),
            description=self._model.overview,
        )

        if self._model.remote_poster is not None:
            embed.set_image(url=self._model.remote_poster)

        return embed

    def markdown(self):
        return f"[{self.pretty_title()}]({self._imdb_url()})"

    def _imdb_url(self):
        return f"{self._IMDB_BASE}/{self._model.imdb_id}"

    @property
    def tmdb_id(self):
        return self._model.tmdb_id


class CuratorException(KinoException):
    pass


class MovieAlreadyAdded(CuratorException):
    pass


class MovieNotFound(CuratorException):
    pass


class RadarrClient:
    def __init__(self, url, api_key, root_folder_path=None):
        self._base = f"{url}/api/v3"

        self._root_folder_path = os.path.join("/media", "Movies") or root_folder_path
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Connection": "keep-alive",
                "Sec-GPC": "1",
                "X-Api-Key": api_key,
            }
        )

    @classmethod
    def from_constants(cls):
        return cls(RADARR_URL, RADARR_TOKEN)

    def add(
        self,
        movie: dict,
        search_for_movie=False,
        quality_profile_id=8,
        monitored=True,
        minimum_availability="announced",
        root_folder_path=None,
    ):
        if movie.get("id"):
            raise MovieAlreadyAdded(movie["title"])

        if movie["added"] != "0001-01-01T00:00:00Z":
            raise MovieAlreadyAdded(movie["title"])

        movie.update(
            {
                "addOptions": {
                    "searchForMovie": search_for_movie,
                },
                "rootFolderPath": root_folder_path or self._root_folder_path,
                "qualityProfileId": quality_profile_id,
                "monitored": monitored,
                "minimumAvailability": minimum_availability,
            }
        )
        response = self._session.post(f"{self._base}/movie", json=movie, verify=False)
        response.raise_for_status()
        return response.json()

    def delete(self, movie_id, delete_files=True, add_import_exclusion=False):
        params = {
            "deleteFiles": delete_files,
            "addImportExclusion": add_import_exclusion,
            "queryParams": "[object Object]",
        }
        response = self._session.delete(
            f"{self._base}/movie/{movie_id}", params=params, verify=False
        )
        response.raise_for_status()
        return None

    def events_in_history(
        self,
        movie_id,
        page=1,
        page_size=40,
    ):
        params = {
            "page": page,
            "pageSize": page_size,
            "sortDirection": "descending",
            "sortKey": "date",
        }

        response = self._session.get(f"{self._base}/history", params=params)
        response.raise_for_status()
        history = response.json()
        try:
            events = [
                item["eventType"]
                for item in history["records"]
                if str(item["movieId"]) == str(movie_id)
            ]
        except (KeyError, IndexError):
            return []

        return events

    def lookup(self, term: str):
        if not term.strip():
            raise MovieNotFound(term)

        params = {"term": term}
        response = self._session.get(f"{self._base}/movie/lookup", params=params)
        response.raise_for_status()
        results = response.json()
        if not results:
            raise MovieNotFound(term)

        return results


def register_movie_addition(user_id, movie_id):
    # This is awful
    Kinobase()._execute_sql(
        "insert into movie_additions (user_id,movie_id) values (?,?)",
        (user_id, movie_id),
    )
