#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import time
import uuid
import tempfile
from functools import cached_property
from typing import List, Optional, Tuple, Type, Union
from urllib import parse

import musicbrainzngs
import requests
import srt
import tmdbsimple as tmdb
from cv2 import cv2
from discord import Embed
from discord_webhook import DiscordEmbed
from fuzzywuzzy import fuzz

import kinobot.exceptions as exceptions

from .cache import region
from .constants import (
    CACHED_FRAMES_DIR,
    FANART_BASE,
    FANART_KEY,
    LOGOS_DIR,
    MET_MUSEUM_BASE,
    MET_MUSEUM_WEBSITE,
    TMDB_IMG_BASE,
    TMDB_KEY,
    WEBSITE,
    YOUTUBE_API_BASE,
    YOUTUBE_API_KEY,
)
from .db import Kinobase, sql_to_dict
from .metadata import EpisodeMetadata, MovieMetadata, get_tmdb_movie
from .utils import (
    clean_url,
    download_image,
    get_dar,
    get_dominant_colors_url,
    get_episode_tuple,
    is_episode,
)

logger = logging.getLogger(__name__)

_TMDB_IMG_BASE = "https://image.tmdb.org/t/p/original"

_CHEVRONS_RE = re.compile("<|>")
_YEAR_RE = re.compile(r"\(([0-9]{4})\)")

tmdb.API_KEY = TMDB_KEY

# By running this software, you are under the agreement of:
#
# None of the sources are actually stored in the bot servers. Every source
# is stored externally, throught cloud services and public databases. In
# the case of cloud services, every source is completely client-side encrypted,
# thus avoiding any form of illegal distribution. In the case of public databases,
# every source is distributed in compliance of the Terms of Service from the
# organizations (MusicBrainz for release metadata, for example).


class LocalMedia(Kinobase):
    "Base class for Media files stored in Kinobot's database."

    id = None
    type = "media"
    table = "movies"

    __insertables__ = ("title",)

    def __init__(self):
        self.id: Optional[Union[str, int]] = None
        self.path: Optional[str] = None
        self.capture = None
        self.fps = 0
        self.language = "en"
        self._dar: Optional[float] = None

    @classmethod
    def from_request(cls, query: str) -> Type[Union[Episode, Movie]]:
        """Get a media subclass by request query.

        :param query:
        :type query: str
        """
        if is_episode(query):
            return Episode

        return Movie

    @property
    def web_url_legacy(self) -> str:
        return f"{WEBSITE}/{self.type}/{self.id}"

    @cached_property
    def subtitle(self) -> str:
        if self.path is None or not os.path.isfile(self.path):  # Undesired
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
        "Update the last request timestamp for the media item."
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
        raise NotImplementedError

    def get_subtitles(self, path: Optional[str] = None) -> List[srt.Subtitle]:
        """
        :raises exceptions.SubtitlesNotFound
        """
        path = path or self.subtitle
        if not os.path.isfile(path):
            raise exceptions.SubtitlesNotFound(path)

        with open(path, "r") as item:
            logger.debug("Looking for subtitle file: %s", path)
            try:
                return list(srt.parse(item))
            except (srt.TimestampParseError, srt.SRTParseError):
                raise exceptions.SubtitlesNotFound(
                    "The subtitles are corrupted. Please report this to the admin."
                ) from None

    def register_post(self, post_id: str):
        "Register a post related to the class."
        sql = f"insert into {self.type}_posts ({self.type}_id, post_id) values (?,?)"
        try:
            self._execute_sql(sql, (self.id, post_id))
        except sqlite3.IntegrityError:  # Parallels
            logger.info("Duplicate ID")

    def get_frame(self, timestamps: Tuple[int, int]):
        return self._get_frame_ffmpeg(timestamps)

    def _get_frame_capture(self, timestamps: Tuple[int, int]):
        """
        Get an image array based on seconds and milliseconds with cv2.
        """
        # fixme
        path_ = (self.path or "").lower()
        if "hevc" in path_ or "265" in path_:
            raise exceptions.InvalidRequest(
                "This format of video is not available. Please wait for the upcoming Kinobot V3"
            )

        if self.capture is None:
            self.load_capture_and_fps()

        seconds, milliseconds = timestamps
        extra_frames = int(self.fps * (milliseconds * 0.001))

        frame_start = int(self.fps * seconds) + extra_frames

        logger.debug("Frame to extract: %s from %s", frame_start, self.path)

        self.capture.set(1, frame_start)
        frame = self.capture.read()[1]

        if frame is not None:
            if self._dar is None:
                self._dar = get_dar(self.path)

            return self._fix_dar(frame)

        raise exceptions.InexistentTimestamp(f"`{seconds}` not found in video")

    def _get_frame_ffmpeg(self, timestamps: Tuple[int, int]):
        ffmpeg_ts = ".".join(str(int(ts)) for ts in timestamps)
        path = os.path.join(tempfile.gettempdir(), f"kinobot_{uuid.uuid4()}.png")

        command = [
            "ffmpeg",
            "-y",
            "-v",
            "quiet",
            "-stats",
            "-ss",
            ffmpeg_ts,
            "-i",
            self.path,
            "-vf",
            "scale=iw*sar:ih",
            "-vframes",
            "1",
            path,
        ]

        logger.debug("Command to run: %s", " ".join(command))
        try:
            subprocess.run(command, timeout=15)
        except subprocess.TimeoutExpired as error:
            raise exceptions.KinoUnwantedException("Subprocess error") from error

        if os.path.isfile(path):
            frame = cv2.imread(path)
            os.remove(path)
            if frame is not None:
                logger.debug("OK")
                return frame

            raise exceptions.InexistentTimestamp(f"`{timestamps}` timestamp not found")

        raise exceptions.InexistentTimestamp(
            f"Internal error extracting '{timestamps}'"
        )

    def load_capture_and_fps(self):  # Still public for GIFs
        logger.info("Loading OpenCV capture and FPS for %s", self.path)
        self.capture = cv2.VideoCapture(self.path)
        self.fps = self.capture.get(cv2.CAP_PROP_FPS)

    def _fix_dar(self, cv2_image):
        """
        Fix aspect ratio from cv2 image array.
        """
        logger.debug("Fixing image with DAR: %s", self._dar)

        width, height = cv2_image.shape[:2]

        # fix width
        fixed_aspect = self._dar / (width / height)
        width = int(width * fixed_aspect)
        return cv2.resize(cv2_image, (width, height))

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

        self.title: Optional[str] = None
        self.og_title: Optional[str] = None
        self.year = None
        self.poster = None
        self.backdrop = None
        self._overview = None
        self.popularity = None
        self.budget = 0
        self.imdb = None
        self.hidden = False
        self.runtime = None
        self._in_db = False

        self._set_attrs_to_values(kwargs)

    @property
    def pretty_title(self) -> str:
        """Classic Kinobot's format title. The original title is used in the
        case of not being equal to the english title.

        :rtype: str
        """
        if (
            self.og_title is not None
            and self.title.lower() != self.og_title.lower()
            and len(self.og_title) < 15
        ):
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
        embed = Embed(
            title=self.simple_title, url=self.web_url, description=self.overview
        )

        if self.web_poster is not None:
            embed.set_thumbnail(url=self.web_poster)

        for director in self.metadata.credits.directors:
            embed.add_field(name="Director", value=director.markdown_url)

        for field in self.metadata.embed_fields:
            embed.add_field(**field)

        embed.add_field(name="Rating", value=self.metadata.rating)

        external = (self.tmdb_md, self.letterboxd_md, self.rym_md)
        embed.add_field(name="External links", value=" • ".join(external))
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

        if self.web_poster is not None:
            embed.set_image(url=self.web_poster)

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
        title = self.title.encode("ascii", "ignore").decode("utf-8")
        return clean_url(f"{title} {self.year} {self.id}")

    @property
    def top_title(self) -> str:
        return f"**{self.metadata.position}.** *{self.simple_title}* (**{self.metadata.rating}**)"

    @property
    def web_url(self) -> str:
        return f"{WEBSITE}/{self.type}/{self.url_clean_title}?lang={self.language}"

    @property
    def relative_url(self) -> str:
        return f"/{self.type}/{self.url_clean_title}"

    @property
    def markdown_url(self) -> str:
        return f"[{self.simple_title}]({self.web_url})"

    @property
    def letterboxd_md(self) -> str:
        return f"[Letterboxd](https://letterboxd.com/tmdb/{self.id})"

    @property
    def tmdb_md(self) -> str:
        return f"[TMDB](https://www.themoviedb.org/movie/{self.id})"

    @property
    def rym_md(self) -> str:  # Experimental
        rym_title = self.og_title.replace(" ", "_").lower()
        return f"[RYM](https://rateyourmusic.com/film/{rym_title})"

    @property
    def web_backdrop(self) -> Union[str, None]:  # Temporary
        return self._handle_image_paths(self.backdrop)

    @property
    def web_poster(self) -> Union[str, None]:  # Temporary
        return self._handle_image_paths(self.poster)

    @staticmethod
    def _handle_image_paths(path: Optional[str] = None):
        if path is None or "Unknown" in path:
            return None

        if path.startswith("/"):
            return TMDB_IMG_BASE + path

        return path

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
        title_query = _YEAR_RE.sub("", query).strip()

        item_list = sql_to_dict(cls.__database__, "select * from movies where hidden=0")

        # First try to find movie by title (almost always happens)
        for item in item_list:
            if title_query == item["title"].lower():
                logger.debug("Movie found by title: %s", item["title"])
                return cls(**item, _in_db=True)

        initial = 0
        final_list = []
        for item in item_list:
            fuzzy = fuzz.ratio(query, f"{item['title'].lower()} ({item['year']})")

            if fuzzy > initial:
                initial = fuzzy
                final_list.append(item)

                if fuzzy > 98:  # Don't waste more time
                    break

        if not final_list:
            raise exceptions.NothingFound

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
        return get_dominant_colors_url(self.web_backdrop or "")

    def load_meta(self):
        if not self._in_db:
            self._load_movie_info_from_tmdb()

        self.metadata.load_and_register()

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


class TVShow(Kinobase):
    "Class for TV Shows stored in the database."
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
            "select * from episodes where tv_show_id=? and hidden=0",
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
        self.hidden = False
        self._overview = None

        self._set_attrs_to_values(kwargs)

    @property
    def pretty_title(self) -> str:
        """Descriptive title that includes title, season, and episode.

        :rtype: str
        """
        title = self.tv_show.title
        return f"{title}\nSeason {self.season}, Episode {self.episode}"

    @property
    def simple_title(self) -> str:
        return f"{self.tv_show.title}: Season {self.season}, Episode {self.episode}"

    @property
    def web_url(self) -> str:
        return f"{WEBSITE}/{self.type}/{self.url_clean_title}"

    @property
    def show_identifier(self) -> str:
        return f"Season {self.season}, Episode {self.episode}"

    @property
    def request_title(self) -> str:
        return f"{self.tv_show.title} S{self.season:02}E{self.episode:02}"

    @cached_property
    def metadata(self) -> EpisodeMetadata:
        return EpisodeMetadata(self.id)

    @property
    def season_title(self):
        return f"{self.tv_show.title} season {self.season}"

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


class ExternalMedia(Kinobase):
    "Base class for external videos."
    type = None

    def __init__(self, **kwargs):
        self.id: Optional[str] = None
        self.category = "Certified"  # Legacy
        self.metadata = None

        self._set_attrs_to_values(kwargs)

    @classmethod
    def from_request(
        cls, query: str
    ) -> Optional[Type[Union[Song, Artwork, AlbumCover]]]:
        """Get a media subclass by request query.

        :param query:
        :type query: str
        """
        for sub in cls.__subclasses__():
            if f"!{sub.type}" in query:
                return sub  # type: ignore

        return None

    @property
    def path(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"

    @property
    def web_url(self) -> str:
        return self.path

    def get_frame(self, timestamps: Tuple[int, int]):
        """
        Get an image array based on seconds and milliseconds with the following
        bash script.

        `video_frame_extractor`

        ```
        #! /bin/bash
        URL="$1"
        TIMESTAMP="$2"
        OUTPUT="$3"

        echo "Video URL: $URL"

        STREAM_URL=$(youtube-dl -g "$URL" -f 'bestvideo[height<=?1080]+\
            bestaudio/best' | head -n 1)

        ffmpeg -y -v quiet -stats -ss "$TIMESTAMP" -i "$STREAM_URL" -vf \
            scale=iw*sar:ih -vframes 1 -q:v 2 "$OUTPUT"
        ```
        """
        seconds, milliseconds = timestamps
        timestamp = f"{seconds}.{milliseconds}"
        logger.info("Extracting %s from %s", timestamp, self.path)

        path = os.path.join(CACHED_FRAMES_DIR, f"{self.id}{seconds}.png")
        command = f"video_frame_extractor {self.path} {timestamp} {path}"

        try:
            subprocess.call(command, stdout=subprocess.PIPE, shell=True, timeout=15)
        except subprocess.TimeoutExpired as error:
            raise exceptions.KinoUnwantedException(error) from None

        if os.path.isfile(path):
            frame = cv2.imread(path)
            os.remove(path)
            if frame is not None:
                return frame

            raise exceptions.InexistentTimestamp(f"`{seconds}` not found")

        raise exceptions.InexistentTimestamp(
            f"External error extracting '{timestamps}' from `{self.path}`"
        )

    def get_subtitles(self, path: Optional[str] = None):
        "Method used just for type consistency."
        if self:
            raise exceptions.InvalidRequest("Songs don't contain quotes")

        return []

    def register_post(self, post_id: str):
        "Method used just for type consistency."
        assert self
        assert post_id


class Song(ExternalMedia):
    "Class for Kinobot songs."
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
        super().__init__()
        self.artist: Optional[str] = None
        self.title: Optional[str] = None

        self._set_attrs_to_values(kwargs)

    @property
    def pretty_title(self) -> str:
        return f"{self.artist} - {self.title}"

    @property
    def markdown_url(self) -> str:
        return f"[{self.simple_title}]({self.path})"

    @property
    def simple_title(self) -> str:
        return self.pretty_title

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


class YTVideo(ExternalMedia):
    "Class for Youtube videos."
    type = "youtube"

    def __init__(self, **kwargs):
        super().__init__()
        self.title: Optional[str] = None
        self.metadata = None

        self._set_attrs_to_values(kwargs)

    @property
    def pretty_title(self) -> str:
        return (self.title or "").title()

    @property
    def simple_title(self) -> str:
        return self.pretty_title

    @property
    def markdown_url(self) -> str:
        return f"[{self.simple_title}]({self.path})"

    @classmethod
    def from_id(cls, item_id: str):
        return cls(id=item_id, title=_get_yt_title(item_id))

    @classmethod
    def from_query(cls, query: str):
        """Find a video by url. Named from_query for the sake of consistency.

        :param query:
        :type query: str
        :param raise_resting: raise exceptions.RestingMovie or not
        :raises:
            exceptions.MovieNotFound
        """
        query = _CHEVRONS_RE.sub("", query)
        video_id = _extract_id_from_url(query)
        title = _get_yt_title(video_id)
        return cls(id=video_id, title=title)


class Artwork(ExternalMedia):
    "Class for artworks."
    type = "artwork"

    def __init__(self, **kwargs):
        super().__init__()
        self.artist: Optional[str] = None
        self.title: Optional[str] = None
        self._id: Optional[str] = None

        self._set_attrs_to_values(kwargs)

        if self._id is not None:
            self.id = str(uuid.uuid3(uuid.NAMESPACE_URL, self._id))

    @property
    def path(self) -> str:
        return str(self._id)

    @property
    def pretty_title(self) -> str:
        return f"{self.artist or 'Unknown'} - {self.title or 'N/A'}"

    @property
    def simple_title(self) -> str:
        return self.pretty_title

    @classmethod
    def from_id(cls, id_):
        msg = (
            f"`{id_}` not found. Please explore available artworks"
            f" on <{MET_MUSEUM_WEBSITE}>. Ask for help on #support.\n\n"
            f"ID example: <{MET_MUSEUM_WEBSITE}/search/726717?searchField=All>"
            " where `726717` is the ID."
        )

        try:
            obj_dict = _get_met_museum_object(id_)
        except requests.RequestException as error:
            logger.error(error, exc_info=True)
            raise exceptions.NothingFound(msg) from None

        from pprint import pprint

        pprint(obj_dict)
        primary_img = obj_dict.get("primaryImage")

        if not primary_img:
            raise exceptions.NothingFound(msg)

        return cls(
            _id=primary_img,
            artist=obj_dict.get("artistDisplayName"),
            title=obj_dict.get("title"),
        )

    @classmethod
    def from_query(cls, query):
        return cls.from_id(query)  # Temporary

    def get_frame(self, timestamps: Tuple[int, int]):
        assert timestamps is not None

        frame = cv2.imread(_get_static_image(self.path))
        if frame is not None:
            return frame

        raise exceptions.NothingFound


class AlbumCover(ExternalMedia):
    "Class for album covers."
    type = "cover"

    def __init__(self, **kwargs):
        super().__init__()
        self.artist: Optional[str] = None
        self.title: Optional[str] = None
        self._id: Optional[str] = None

        self._set_attrs_to_values(kwargs)

        if self._id is not None:
            self.id = str(uuid.uuid3(uuid.NAMESPACE_URL, self._id))

    @property
    def path(self) -> str:
        return str(self._id)

    @property
    def pretty_title(self) -> str:
        return f"{self.artist} - {self.title}"

    @property
    def simple_title(self) -> str:
        return self.pretty_title

    @classmethod
    def from_id(cls, id_):
        return cls.from_query(id_)  # Temporary

    @classmethod
    def from_query(cls, query):
        try:
            album = _get_mb_album(query)
        except musicbrainzngs.MusicBrainzError as error:
            logger.error(error, exc_info=True)
            raise exceptions.NothingFound

        image = album.get("images", [{}])[0].get("image")

        if not image:
            raise exceptions.NothingFound

        return cls(
            _id=image,
            artist=album.get("artist-credit-phrase", "Unknown"),
            title=album.get("title"),
        )

    def get_frame(self, timestamps: Tuple[int, int]):
        assert timestamps is not None

        frame = cv2.imread(_get_static_image(self.path))
        if frame is not None:
            return frame

        raise exceptions.NothingFound


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
def _find_fanart(item_id: int, is_tv: bool = False) -> list:
    """Try to find a list of logo dicts from Fanart.

    :param item_id:
    :type item_id: int
    :param is_tv:
    :type is_tv: bool
    :rtype: list
    """
    base = FANART_BASE + ("/tv" if is_tv else "/movies")

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
    if not logos and not is_tv:
        logos = result.get("movielogo")

    return logos


@region.cache_on_arguments()
def _get_mb_album(query: str) -> dict:
    musicbrainzngs.set_useragent("Kinobot Search", "0.0.1")

    results = musicbrainzngs.search_release_groups(query, limit=1, strict=True)
    try:
        album = results["release-group-list"][0]
    except (KeyError, IndexError):
        raise exceptions.NothingFound from None

    images = musicbrainzngs.get_release_group_image_list(album["id"])
    album.update(images)

    return album


def _get_static_image(url: str):
    img = str(uuid.uuid3(uuid.NAMESPACE_URL, url))
    path = os.path.join(CACHED_FRAMES_DIR, img)
    if os.path.isfile(path):
        return path

    return download_image(url, path)


@region.cache_on_arguments()
def _get_yt_title(video_id: str):
    params = {
        "id": video_id,
        "part": "snippet",
        "key": YOUTUBE_API_KEY,
    }
    response = requests.get(YOUTUBE_API_BASE, params=params)
    video = response.json()
    if not video.get("items"):
        raise exceptions.NothingFound

    title = video["items"][0].get("snippet", {}).get("title")

    if title is None:
        raise exceptions.NothingFound

    return title


@region.cache_on_arguments()
def _get_met_museum_object(id_) -> dict:
    response = requests.get(f"{MET_MUSEUM_BASE}/objects/{id_}")
    return response.json()


def _extract_id_from_url(video_url: str) -> str:
    """
    :param video_url: YouTube URL (classic or mobile)
    """
    video_url = video_url.strip()
    parsed = parse.parse_qs(parse.urlparse(video_url).query).get("v")
    if parsed is not None:
        return parsed[0]

    # Mobile fallback
    if "youtu.be" in video_url:
        parsed = parse.urlsplit(video_url)
        return parsed.path.replace("/", "")

    raise exceptions.InvalidRequest(f"Invalid video URL: {video_url}")


# Type hints
hints = Union[Episode, Movie, Song, AlbumCover, Artwork]
