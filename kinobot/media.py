#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import os
import sqlite3
import subprocess
import time
from functools import cached_property
from typing import List, Optional, Tuple, Union

import requests
import srt
import tmdbsimple as tmdb
from cv2 import cv2
from discord import Embed
from discord_webhook import DiscordEmbed
from fuzzywuzzy import fuzz

import kinobot.exceptions as exceptions

from .cache import region
from .constants import FANART_BASE, FANART_KEY, LOGOS_DIR, TMDB_KEY, WEBSITE
from .db import Kinobase, sql_to_dict
from .metadata import EpisodeMetadata, MovieMetadata, get_tmdb_movie
from .utils import (clean_url, download_image, get_dominant_colors_url,
                    get_episode_tuple)

logger = logging.getLogger(__name__)

_TMDB_IMG_BASE = "https://image.tmdb.org/t/p/original"

tmdb.API_KEY = TMDB_KEY


class LocalMedia(Kinobase):
    " Base class for Media files stored in Kinobot's database. "

    id = None
    type = "media"
    table = "movies"
    path = "Unknown"
    capture = None
    fps = 0

    last_request = 0

    __insertables__ = ("title",)

    def __init__(self):
        self.id = None
        self.path = ""
        self.capture = None
        self.fps = 0
        self.last_request = 0

    @property
    def web_url_legacy(self) -> str:
        return f"{WEBSITE}/{self.type}/{self.id}"

    @cached_property
    def subtitle(self) -> str:
        if not os.path.isfile(self.path):  # Undesired
            raise FileNotFoundError(self.path)

        sub_file = os.path.splitext(self.path)[0] + ".en.srt"

        if not os.path.isfile(sub_file):
            raise exceptions.SubtitlesNotFound(
                "Subtitles not found. Please report this to the admin."
            )

        return os.path.splitext(self.path)[0] + ".en.srt"

    def register(self):
        "Register item in the database."
        try:
            self._insert()
        except sqlite3.IntegrityError:
            logger.info("Already registered. Updating")
            self.update()

    def update(self):
        "Update all the collums in the database for item from attributes."
        self._update(self.id)

    def update_last_request(self):
        " Update the last request timestamp for the media item. "
        timestamp = int(time.time())

        command = f"update {self.table} set last_request=? where id=?"
        params = (
            timestamp,
            self.id,
        )

        self._execute_sql(command, params)

    def sync_subtitles(self):
        """
        Try to synchronize subtitles using `ffsubsync`.

        raises subprocess.TimeoutExpired
        """
        command = (
            f"ffs '{self.path}' -i '{self.subtitle}' -o '{self.subtitle}' "
            "--max-offset-seconds 180 --vad webrtc"
        )

        logger.info("Command: %s", command)

        subprocess.call(command, stdout=subprocess.PIPE, shell=True, timeout=900)

    def load_capture_and_fps(self):
        """Callable used to save resources for long requests."""
        if self.type != "song":
            logger.debug("Loading OpenCV capture and FPS for %s", self.path)
            self.capture = cv2.VideoCapture(self.path)
            self.fps = self.capture.get(cv2.CAP_PROP_FPS)
            logger.debug("FPS: %s", self.fps)

    def check_media_availability(self):
        """
        :raises exceptions.RestingMovie
        """
        limit = int(time.time()) - 120000

        if self.last_request > limit:
            raise exceptions.RestingMovie

    def get_subtitles(self, path: Optional[str] = None) -> List[srt.Subtitle]:
        """
        :raises exceptions.SubtitlesNotFound
        """
        path = path or self.subtitle

        with open(path, "r") as item:
            logger.debug("Looking for subtitle file: %s", path)
            try:
                return list(srt.parse(item))
            except (srt.TimestampParseError, srt.SRTParseError):
                raise exceptions.SubtitlesNotFound(
                    "The subtitles are corrupted. Please report this to the admin."
                ) from None

    def register_post(self, post_id: str):
        " Register a post related to the class. "
        sql = f"insert into {self.type}_posts ({self.type}_id, post_id) values (?,?)"

        self._execute_sql(sql, (self.id, post_id))

    def _get_insert_command(self) -> str:
        columns = ",".join(self.__insertables__)
        placeholders = ",".join("?" * len(self.__insertables__))
        return f"insert into {self.table} ({columns}) values ({placeholders})"

    def __repr__(self):
        return f"<Media {self.type}: {self.path} ({self.id})>"


class Movie(LocalMedia):
    """Class for movies stored locally in Kinobot's database."""

    table = "movies"
    type = "movie"

    __insertables__ = (
        "title",
        "og_title",
        "year",
        "poster",
        "backdrop",
        "path",
        "overview",
        "popularity",
        "budget",
        "id",
        "imdb",
        "hidden",
    )

    def __init__(self, **kwargs):
        super().__init__()

        self.title: Union[str, None] = None
        self.og_title: Union[str, None] = None
        self.year = None
        self.poster = None
        self.backdrop = None
        self._overview = None
        self.popularity = None
        self.budget = 0
        self.imdb = None
        self.runtime = None
        self._in_db = False

        self._set_attrs_to_values(kwargs)

    @property
    def pretty_title(self) -> str:
        """Classic Kinobot's format title. The original title is used in the
        case of not being equal to the english title.

        :rtype: str
        """
        assert self.og_title is not None

        if self.title.lower() != self.og_title.lower() and len(self.og_title) < 30:
            return f"{self.og_title} [{self.title}] ({self.year})"

        return f"{self.title} ({self.year})"

    @property
    def overview(self) -> Union[str, None]:
        return self._overview

    @overview.setter
    def overview(self, val: str):
        self._overview = val[:250] + "..." if len(val) > 199 else ""

    @cached_property
    def metadata(self) -> MovieMetadata:
        return MovieMetadata(self.id)

    @cached_property
    def embed(self) -> Embed:
        """Discord embed used for Discord searchs.

        :rtype: Embed
        """
        assert self.metadata is not None

        embed = Embed(
            title=self.simple_title, url=self.web_url, description=self.overview
        )

        embed.set_thumbnail(url=self.poster)

        directors = self.metadata.credits.directors

        if directors:
            embed.set_author(name=directors[0].name, url=directors[0].web_url)

        for field in self.metadata.embed_fields:
            embed.add_field(**field)

        embed.add_field(name="Rating", value=self.metadata.rating)

        return embed

    @cached_property
    def webhook_embed(self) -> DiscordEmbed:
        """Embed used for webhooks about newly added movies.

        :rtype: DiscordEmbed
        """
        embed = DiscordEmbed(
            title=self.pretty_title,
            description=self.overview,
            url=self.web_url,
        )

        embed.set_author(name=f"Kinobot's {self.type} addition", url=WEBSITE)

        if self.poster is not None:
            embed.set_image(url=self.poster)

        for director in self.metadata.credits.directors:
            embed.add_embed_field(name="Director", value=director.markdown_url)

        embed.set_timestamp()

        return embed

    @property
    def simple_title(self) -> str:
        """A basic title including the year.

        :rtype: str
        """
        return f"{self.title} ({self.year})"

    @cached_property
    def url_clean_title(self) -> str:
        """Url-friendly title used in the website.

        :rtype: str
        """
        return clean_url(f"{self.title} {self.year} {self.id}")

    @property
    def web_url(self) -> str:
        return f"{WEBSITE}/{self.type}/{self.url_clean_title}"

    @property
    def relative_url(self) -> str:
        return f"/{self.type}/{self.url_clean_title}"

    @property
    def markdown_url(self) -> str:
        return f"[{self.simple_title}]({self.web_url})"

    @classmethod
    def from_subtitle_basename(cls, path: str):
        """Search an item based on the subtitle path.

        :param path:
        :type path: str
        :raises exceptions.NothingFound
        """
        return cls(**_find_from_subtitle(cls.__database__, cls.table, path))

    @classmethod
    def from_id(cls, id_: int):
        """Load the item from its ID.

        :param id_:
        :type id_: int
        """
        movie = sql_to_dict(cls.__database__, "select * from movies where id=?", (id_,))
        if not movie:
            raise exceptions.MovieNotFound(f"ID not found in database: {id_}")

        return cls(**movie[0], _in_db=True)

    @classmethod
    def from_web(cls, url: str):
        """Load the item from its ID.

        :param id_:
        :type id_: int
        """
        item_id = url.split("-")[-1]  # id
        return cls.from_id(int(item_id))

    @classmethod
    def from_query(cls, query: str):
        """Find a movie by query (fuzzy search).

        :param query:
        :type query: str
        :raises:
            exceptions.MovieNotFound
        """
        query = query.lower().strip()
        item_list = sql_to_dict(cls.__database__, "select * from movies where hidden=0")

        # We use loops for year and og_title matching
        initial = 0
        final_list = []
        for item in item_list:
            fuzzy = fuzz.ratio(query, f"{item['title']} {item['year']}".lower())

            if fuzzy > initial:
                initial = fuzzy
                final_list.append(item)

        item = final_list[-1]

        if initial < 59:
            raise exceptions.MovieNotFound(
                f'Movie not found: "{query}". Maybe you meant "{item["title"]}"? '
                f"Explore the collection: {WEBSITE}."
            )

        return cls(**item, _in_db=True)

    @classmethod
    def from_radarr(cls, item: dict):
        movie = dict()

        movie["path"] = item.get("movieFile").get("path")
        movie["title"] = item.get("title")
        movie["runtime"] = item.get("runtime")
        movie["id"] = item["tmdbId"]

        return cls(**movie)

    @classmethod
    def from_tmdb(cls, item: dict):
        item["backdrop"] = item.get("backdrop_path")
        item["poster"] = item.get("poster_path")
        item["year"] = item.get("release_date")[:4]

        return cls(**item)

    @cached_property
    def logo(self) -> Union[str, None]:
        logo = os.path.join(LOGOS_DIR, f"{self.id}_{self.type}.png")

        # Try to avoid extra recent API calls
        if os.path.isfile(logo):
            logger.info("Found saved logo: %s", logo)
            return logo

        logos = _find_fanart(self.id)

        try:
            url = next(logo.get("url") for logo in logos if logo.get("lang") == "en")
            download_image(url, logo)
            return logo
        except (StopIteration, TypeError):
            return None

    @cached_property
    def dominant_colors(self) -> Tuple[tuple, tuple]:
        return get_dominant_colors_url(self.backdrop or "")

    def _load_movie_info_from_tmdb(self, movie: Optional[dict] = None):
        if movie is None:
            movie = get_tmdb_movie(self.id)

        for key, val in movie.items():
            if hasattr(self, key):
                logger.debug("Setting attribute from TMDB: %s: %s", key, val)
                setattr(self, key, val)

        self.imdb = movie.get("imdb_id", "Unknown")
        self.og_title = movie.get("original_title", self.title)
        self.year = movie.get("release_date", "")[:4]
        self.poster = movie.get("poster_path")
        self.backdrop = movie.get("backdrop_path")

    def load_meta(self):
        if not self._in_db:
            self._load_movie_info_from_tmdb()

        self.metadata.load_and_register()


class TVShow(Kinobase):
    " Class for TV Shows stored in the database. "
    table = "tv_shows"

    __insertables__ = (
        "id",
        "name",
        "overview",
        "backdrop_path",
        "poster_path",
        "popularity",
        "first_air_date",
        "last_air_date",
        "status",
        "imdb",
        "tvdb",
    )

    def __init__(self, **kwargs):
        self.id = None
        self.name = None
        self.overview = None
        self.backdrop_path = None
        self.poster_path = None
        self.popularity = None
        self.first_air_date = None
        self.last_air_date = None
        self.status = None
        self.imdb = None
        self.tvdb = None

        self._set_attrs_to_values(kwargs)

    def register(self):
        self._insert()

    @classmethod
    def from_query(cls, query: str):
        """Find a TV Show by query (fuzzy search).

        :param query:
        :type query: str
        :param raise_resting: raise exceptions.RestingMovie or not
        :raises:
            exceptions.EpisodeNotFound
        """
        query = query.lower().strip()
        item_list = sql_to_dict(cls.__database__, "select * from tv_shows")

        # We use loops for year and og_title matching
        initial = 0
        final_list = []
        for item in item_list:
            fuzzy = fuzz.ratio(query, item["name"].lower())

            if fuzzy > initial:
                initial = fuzzy
                final_list.append(item)

        item = final_list[-1]

        if initial < 77:
            raise exceptions.EpisodeNotFound(
                f'TV Show not found: "{query}". Maybe you meant "{item["name"]}"? '
                f"Explore the collection: {WEBSITE}."
            )

        return cls(**item)

    @classmethod
    def from_id(cls, tv_id):
        result = sql_to_dict(
            cls.__database__, "select * from tv_shows where id=?", (tv_id,)
        )
        if result:
            return cls(**result[0])

        raise exceptions.EpisodeNotFound("ID not found in TV shows table")

    @classmethod
    def from_web(cls, url: str):
        item_id = url.split("-")[-1]
        return cls.from_id(item_id)

    @property
    def embed(self) -> Embed:
        embed = Embed(
            title=self.simple_title, url=self.web_url, description=self.overview
        )

        if self.poster_path is not None:
            embed.set_thumbnail(url=_TMDB_IMG_BASE + self.poster_path)

        if self.episodes:
            embed.add_field(name="Episodes in the database", value=len(self.episodes))
        else:
            embed.add_field(name="Episodes in the database", value="Nothing found")

        # F-strings to avoid NoneTypes
        embed.add_field(name="Status", value=f"{self.status}")
        embed.add_field(
            name="Aired", value=f"{self.first_air_date} to {self.last_air_date}"
        )

        return embed

    @property
    def markdown_url(self) -> str:
        return f"[{self.simple_title}]({self.web_url})"

    @property
    def web_url(self) -> str:
        return f"{WEBSITE}/tv/{self.url_clean_title}"

    @property
    def relative_url(self) -> str:
        return f"/tv/{self.url_clean_title}"

    @cached_property
    def url_clean_title(self) -> str:
        return clean_url(f"{self.title} {self.id}")

    @property
    def title(self):  # Consistency
        return self.name

    @property
    def simple_title(self):  # Consistency
        return self.name

    @cached_property
    def episodes(self):
        results = self._db_command_to_dict(
            "select * from episodes where tv_show_id=?",
            (self.id,),
        )
        if results:
            return [Episode(**item) for item in results]

        return []

    @cached_property
    def logo(self) -> Union[str, None]:
        logo = os.path.join(LOGOS_DIR, f"{self.id}_show.png")

        # Try to avoid extra recent API calls
        if os.path.isfile(logo):
            logger.info("Found saved logo")
            return logo

        logos = _find_fanart(self.tvdb, True)

        try:
            url = next(logo.get("url") for logo in logos if logo.get("lang") == "en")
            download_image(url, logo)
            return logo
        except (StopIteration, TypeError):
            return None

    @cached_property
    def dominant_colors(self) -> Tuple[tuple, tuple]:
        # Ignore NoneType with f-strings as the function will return colors anyway
        return get_dominant_colors_url(f"{_TMDB_IMG_BASE}{self.backdrop_path}")

    def __repr__(self) -> str:
        return f"<TV Show {self.title} ({self.id})>"


class Episode(LocalMedia):
    """Class for episodes stored locally in Kinobot's database."""

    type = "episode"
    table = "episodes"

    __insertables__ = (
        "tv_show_id",
        "season",
        "episode",
        "title",
        "path",
        "overview",
        "id",
        "hidden",
    )

    def __init__(self, **kwargs):
        super().__init__()

        self._tv_show = None
        self.season = None
        self.tv_show_id = None
        self.episode = None
        self.title = None
        self._overview = None

        self._set_attrs_to_values(kwargs)

    @property
    def pretty_title(self) -> str:
        """Descriptive title that includes title, season, and episode.

        :rtype: str
        """
        return f"{self.tv_show.title} - Season {self.season}, Episode {self.episode}"

    @property
    def simple_title(self) -> str:
        return f"{self.tv_show.title} S{self.season:02}E{self.episode:02}"

    @property
    def web_url(self) -> str:
        return f"{WEBSITE}/{self.type}/{self.url_clean_title}"

    @property
    def show_identifier(self) -> str:
        return f"Season {self.season}, Episode {self.episode}"

    @cached_property
    def metadata(self) -> EpisodeMetadata:
        return EpisodeMetadata(self.id)

    @property
    def markdown_url(self) -> str:
        return f"[{self.simple_title}]({self.web_url})"

    @property
    def url_clean_title(self) -> str:
        return clean_url(f"{self.pretty_title} {self.id}")

    @property
    def relative_url(self) -> str:
        return f"/{self.type}/{self.url_clean_title}"

    @property
    def logo(self) -> Union[str, None]:
        return self.tv_show.logo

    @property
    def backdrop(self) -> Union[str, None]:
        return self.tv_show.backdrop_path

    @property
    def overview(self) -> Union[str, None]:
        return self._overview

    @overview.setter
    def overview(self, val: str):
        self._overview = val  # [:200] + "..." if len(val) > 199 else ""

    @cached_property
    def embed(self) -> Embed:
        """Embed used for Discord searchs.

        :rtype: Embed
        """
        embed = Embed(
            title=self.simple_title, url=self.web_url, description=self.overview
        )
        return embed

    @cached_property
    def tv_show(self) -> TVShow:
        if self._tv_show is not None:
            return self._tv_show

        return TVShow.from_id(self.tv_show_id)

    @property
    def dominant_colors(self) -> Tuple[tuple, tuple]:
        return self.tv_show.dominant_colors

    @classmethod
    def from_subtitle_basename(cls, path: str):
        return cls(**_find_from_subtitle(cls.__database__, cls.table, path))

    @classmethod
    def from_id(cls, id_: int):
        episode = sql_to_dict(
            cls.__database__, "select * from episodes where id=?", (id_,)
        )
        if not episode:
            raise exceptions.EpisodeNotFound(f"ID not found in database: {id_}")

        return cls(**episode[0])

    @classmethod
    def from_web(cls, url: str):
        item_id = url.split("-")[-1]
        return cls.from_id(int(item_id))

    @classmethod
    def from_register_dict(cls, item: dict):
        return cls(
            season=item["season_number"],
            episode=item["episode_number"],
            title=item["name"],
            metadata=EpisodeMetadata(item["id"], item),
            **item,
        )

    @classmethod
    def from_query(cls, query: str):
        """
        :param query:
        :type query: str
        :raises exceptions.EpisodeNotFound
        """
        season, episode = get_episode_tuple(query)
        tv_show = TVShow.from_query(query[:-6])
        result = sql_to_dict(
            cls.__database__,
            "select * from episodes where (tv_show_id=? and season=? and episode=?)",
            (
                tv_show.id,
                season,
                episode,
            ),
        )
        if result:
            return cls(_tv_show=tv_show, **result[0])

        raise exceptions.EpisodeNotFound(f"Episode not found: {query}")

    def load_meta(self):
        self.metadata.load_and_register()


class Song(Kinobase):
    " Class for Kinobot songs. "
    table = "songs"
    type = "song"

    __insertables__ = (
        "title",
        "artist",
        "id",
        "category",
        "hidden",
    )

    def __init__(self, **kwargs):
        self.title = None
        self.artist = None
        self.id = None
        self.category = None

        self._set_attrs_to_values(kwargs)

    @property
    def pretty_title(self) -> str:
        return f"{self.artist} - {self.title}"

    @property
    def simple_title(self) -> str:
        return self.pretty_title

    @property
    def web_url(self) -> str:
        return self.path

    @property
    def path(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"

    @property
    def markdown_url(self) -> str:
        return f"[{self.simple_title}]({self.path})"

    @classmethod
    def from_id(cls, id_: int):
        song = sql_to_dict(cls.__database__, "select * from songs where id=?", (id_,))
        if not song:
            raise exceptions.NothingFound(f"ID not found in database: {id_}")

        return cls(**song[0])

    @classmethod
    def from_query(cls, query: str):
        """Find a song by query (fuzzy search).

        :param query:
        :type query: str
        :param raise_resting: raise exceptions.RestingMovie or not
        :raises:
            exceptions.MovieNotFound
        """
        query = query.lower().strip()
        item_list = sql_to_dict(cls.__database__, "select * from songs")

        # We use loops for year and og_title matching
        initial = 0
        final_list = []
        for item in item_list:
            fuzzy = fuzz.ratio(query, f"{item['artist']} - {item['title']}".lower())

            if fuzzy > initial:
                initial = fuzzy
                final_list.append(item)

        item = final_list[-1]

        if initial < 59:
            raise exceptions.NothingFound(
                f'Song not found: "{query}". Maybe you meant "{item["title"]}"? '
                f"Explore the collection: {WEBSITE}/music."
            )

        return cls(**item, _in_db=True)


# Utils


def _find_from_subtitle(database: str, table: str, path: str) -> dict:
    """
    :param path:
    :type path: str
    :rtype: dict
    :raises exceptions.NothingFound
    """
    path = path.replace(".en.srt", "")
    result = sql_to_dict(
        database,
        f"select * from {table} where instr(path, ?) > 0;",
        (path,),
    )

    if result:
        return result[0]

    raise exceptions.NothingFound(f"Basename not found in database: {path}")


# Cached functions


@region.cache_on_arguments()
def _find_fanart(item_id: int, istv: bool = False) -> list:
    """Try to find a list of logo dicts from Fanart.

    :param item_id:
    :type item_id: int
    :param istv:
    :type istv: bool
    :rtype: list
    """
    base = FANART_BASE + ("/tv" if istv else "/movies")

    logger.debug("Base: %s", base)
    try:
        r = requests.get(
            f"{base}/{item_id}", params={"api_key": FANART_KEY}, timeout=10
        )
        r.raise_for_status()
    except requests.RequestException as error:
        logger.error(error, exc_info=True)
        return []

    result = json.loads(r.content)
    logos = result.get("hdmovielogo") or result.get("hdtvlogo")
    if not logos and not istv:
        logos = result.get("movielogo")

    return logos
