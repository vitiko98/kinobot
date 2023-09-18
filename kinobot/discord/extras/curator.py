import datetime
import logging
import os
from typing import List, Optional, Dict

from discord import Embed
import pydantic
import requests

from kinobot.constants import RADARR_ROOT_DIR
from kinobot.constants import RADARR_TOKEN
from kinobot.constants import RADARR_URL
from kinobot.constants import SONARR_ROOT_DIR
from kinobot.constants import SONARR_TOKEN
from kinobot.constants import SONARR_URL
from kinobot.db import Kinobase
from kinobot.exceptions import KinoException

logger = logging.getLogger(__name__)


def _to_camel(string: str) -> str:
    result = "".join(word.capitalize() for word in string.split("_"))
    return result[0].lower() + result[1:]


class RadarrMovie(pydantic.BaseModel):
    added: Optional[datetime.datetime]
    clean_title: str
    folder_name: str
    has_file: bool
    id: int
    imdb_id: Optional[str]
    is_available: bool
    minimum_availability: str
    monitored: bool
    movie_file: Optional[Dict]
    original_title: str
    path: str
    quality_profile_id: int
    runtime: int
    size_on_disk: int
    sort_title: str
    status: str
    studio: str
    title: str
    title_slug: str
    tmdb_id: int
    website: str
    year: int

    class Config:
        alias_generator = _to_camel


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


_IMDB_BASE = "https://www.imdb.com/title"


class SonarrEpisodeFileModel(pydantic.BaseModel):
    season_number: int

    class Config:
        alias_generator = _to_camel


class _Season(pydantic.BaseModel):
    season_number: int

    class Config:
        alias_generator = _to_camel


class SonarrTVShowModel(pydantic.BaseModel):
    added: str
    title: str
    folder: str
    tvdb_id: int
    path: Optional[str] = None
    year = 0
    overview = ""
    imdb_id: Optional[str] = None
    remote_poster: Optional[str] = None
    seasons: List[_Season]

    class Config:
        alias_generator = _to_camel

    def already_added(self):
        return self.path is not None

    def embed(self) -> Embed:
        """Discord embed used for Discord searchs.

        :rtype: Embed
        """
        embed = Embed(
            title=self.title,
            description=self.overview,
        )

        if self.remote_poster is not None:
            embed.set_image(url=self.remote_poster)

        return embed

    def pretty_title(self):
        return f"{self.title} ({self.year})"

    def markdown(self):
        return f"[{self.title}]({self._imdb_url()})"

    def _imdb_url(self):
        return f"{_IMDB_BASE}/{self.imdb_id}"


class MovieView:
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

        # if self.to_be_added():
        #    title = f"{title} (To be added)"

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
        return f"{_IMDB_BASE}/{self._model.imdb_id}"

    @property
    def tmdb_id(self):
        return self._model.tmdb_id


class _Quality(pydantic.BaseModel):
    name = "Unknown"
    resolution = 480


class ReleaseModel(pydantic.BaseModel):
    size: int
    guid: str
    indexer_id: int
    movie_id: int
    rejected: bool
    rejections = []
    seeders: int
    quality: _Quality
    title = "Unknown"

    @pydantic.validator("quality", pre=True, always=True)
    def set_ts_now(cls, v):
        try:
            return _Quality(**v["quality"])
        except KeyError:
            return _Quality()

    class Config:
        alias_generator = _to_camel

    def pretty_title(self):
        title = f"{self.quality.name} ({self.size/float(1<<30):,.1f} GB)"

        if self.rejected:
            title = f"{title} (requires manual import by admin)"

        if "extras" in self.title.lower():
            title = f"{title} (possible 'extras' release)"

        if "remux" in self.title.lower():
            title = f"{title} (REMUX - avoid this!)"

        return title


class ReleaseModelSonarr(pydantic.BaseModel):
    size: int
    guid: str
    indexer_id: int
    series_id: int
    full_season: bool
    rejected: bool
    rejections = []
    seeders: int
    quality: _Quality
    title = "Unknown"

    @pydantic.validator("quality", pre=True, always=True)
    def set_ts_now(cls, v):
        try:
            return _Quality(**v["quality"])
        except KeyError:
            return _Quality()

    class Config:
        alias_generator = _to_camel

    def pretty_title(self):
        title = f"{self.quality.name} ({self.size/float(1<<30):,.1f} GB)"

        if self.rejected:
            title = f"{title} ({self.rejections[0]}) [Manual import]"

        if "extras" in self.title.lower():
            title = f"{title} (possible 'extras' release)"

        return title


class Statistics(pydantic.BaseModel):
    size_on_disk = 0

    class Config:
        alias_generator = _to_camel


class SonarrTVShow(pydantic.BaseModel):
    id: int
    title: str
    tvdb_id: Optional[int]
    series_type: Optional[str]
    imdb_id: Optional[str]
    added: Optional[datetime.datetime]
    statistics: Optional[Statistics]

    class Config:
        alias_generator = _to_camel


class CuratorException(KinoException):
    pass


class MovieAlreadyAdded(CuratorException):
    pass


class MovieNotFound(CuratorException):
    pass


class RadarrClient:
    def __init__(self, url, api_key, root_folder_path=None):
        self._base = f"{url}/api/v3"

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Connection": "keep-alive",
                "Sec-GPC": "1",
                "X-Api-Key": api_key,
            }
        )
        if root_folder_path is None:
            self._root_folder_path = self._get_root_folder()
        else:
            self._root_folder_path = root_folder_path

        logger.debug("Client started: %s (%s)", self._base, self._root_folder_path)

    def _get_root_folder(self):
        response = self._session.get(f"{self._base}/rootFolder", verify=False)
        response.raise_for_status()

        try:
            return response.json()[0]["path"]
        except (IndexError, KeyError) as error:
            logger.error("Error trying to get root foolder: %s", error)
            return None

    @classmethod
    def from_constants(cls):
        return cls(RADARR_URL, RADARR_TOKEN)

    def movie(self):
        response = self._session.get(f"{self._base}/movie")
        return [RadarrMovie(**item) for item in response.json()]

    def add(
        self,
        movie: dict,
        search_for_movie=False,
        quality_profile_id=1,
        monitored=True,
        minimum_availability="announced",
        root_folder_path=None,
    ):
        if movie.get("id"):
            logger.debug("Movie already added")
            return movie
            # raise MovieAlreadyAdded(movie["title"])

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

    def manual_search(self, movie_id):
        response = self._session.get(
            f"{self._base}/release", params={"movieId": movie_id}
        )
        response.raise_for_status()
        result = response.json()
        for release in result:
            release["movieId"] = movie_id

        return result

    def add_to_download_queue(self, movie_id, guid, indexer_id):
        json_data = {
            "guid": guid,
            "indexerId": indexer_id,
            "movieId": movie_id,
        }

        response = self._session.post(
            f"{self._base}/release", json=json_data, verify=False
        )
        try:
            logger.debug(response.json())
        except:
            pass
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


class SonarrClient:
    def __init__(self, url, api_key, root_folder_path=None):
        self._session = requests.Session()
        self._base = f"{url}/api/v3"

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Connection": "keep-alive",
                "Sec-GPC": "1",
                "X-Api-Key": api_key,
            }
        )
        if root_folder_path is None:
            self._root_folder_path = self._get_root_folder()
        else:
            self._root_folder_path = root_folder_path

        logger.debug("Client started: %s (%s)", self._base, self._root_folder_path)

    def _get_root_folder(self):
        response = self._session.get(f"{self._base}/rootFolder", verify=False)
        response.raise_for_status()

        try:
            return response.json()[0]["path"]
        except (IndexError, KeyError) as error:
            logger.error("Error trying to get root foolder: %s", error)
            return None

    @classmethod
    def from_constants(cls):
        return cls(SONARR_URL, SONARR_TOKEN)

    def lookup(self, term: str):
        params = {
            "term": term,
        }
        response = self._session.get(
            f"{self._base}/series/lookup", params=params, verify=False
        )
        response.raise_for_status()
        return response.json()

    def add(
        self,
        tv_show: dict,
        search_for_missing_episodes=False,
        quality_profile_id=1,
        language_profile_id=1,
        monitored=False,
        root_folder_path=None,
    ):
        if tv_show.get("id"):
            return tv_show

        tv_show.update(
            {
                "addOptions": {
                    "searchForMissingEpisodes": search_for_missing_episodes,
                    "searchForCutoffUnmetEpisodes": False,
                },
                "rootFolderPath": root_folder_path or self._root_folder_path,
                "qualityProfileId": quality_profile_id,
                "languageProfileId": language_profile_id,
                "monitored": monitored,
            }
        )

        response = self._session.post(
            f"{self._base}/series", json=tv_show, verify=False
        )
        response.raise_for_status()
        return response.json()

    def manual_search(self, series_id, season_number):
        params = {
            "seriesId": series_id,
            "seasonNumber": season_number,
        }

        response = self._session.get(f"{self._base}/release", params=params)
        response.raise_for_status()
        return response.json()

    def add_to_download_queue(self, guid, indexer_id):
        json_data = {"guid": guid, "indexerId": indexer_id}

        response = self._session.post(
            f"{self._base}/release", json=json_data, verify=False
        )

        response.raise_for_status()
        return response.json()

    def episode_file(self, series_id):
        params = {
            "seriesId": series_id,
        }
        response = self._session.get(
            f"{self._base}/episodeFile", params=params, verify=False
        )
        return response.json()

    def events_in_history(
        self,
        series_id,
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
                item
                for item in history["records"]
                if str(item["seriesId"]) == str(series_id)
            ]
        except (KeyError, IndexError):
            return []

        return events

    def series(self):
        response = self._session.get(f"{self._base}/series")

        response.raise_for_status()

        return [SonarrTVShow(**item) for item in response.json()]

    def series_delete(self, id, delete_files=True, add_import_exclusion=False):
        params = {
            "deleteFiles": delete_files,
            "addImportListExclusion": add_import_exclusion,
            "queryParams": "[object Object]",
        }

        response = self._session.delete(
            f"{self._base}/series/{id}", params=params, verify=False
        )
        response.raise_for_status()
        return None


def register_movie_addition(user_id, movie_id):
    # This is awful
    Kinobase()._execute_sql(
        "insert into movie_additions (user_id,movie_id) values (?,?)",
        (user_id, movie_id),
    )


def register_tv_show_season_addition(user_id, tv_show_id, season_number):
    # This is awful
    Kinobase()._execute_sql(
        "insert into tv_show_season_additions (user_id,tv_show_id,season_number) values (?,?,?)",
        (user_id, tv_show_id, season_number),
    )
