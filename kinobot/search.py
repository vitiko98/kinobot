#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import os
import re
from functools import cached_property
from operator import itemgetter
from random import shuffle
from typing import Generator, List, Union

import tmdbsimple as tmdb
from discord import Embed
from fuzzywuzzy import fuzz
from ripgrepy import Ripgrepy

import kinobot.exceptions as exceptions

from .cache import region
from .constants import SUBS_DIR, TMDB_KEY
from .db import Kinobase
from .media import Episode, Movie, Song, TVShow
from .metadata import Category, Country, Genre, Person
from .request import Request
from .utils import is_episode

tmdb.API_KEY = TMDB_KEY

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r".*([1-3][0-9]{3})")


class MovieSearch(Kinobase):
    def __init__(self, query: str, limit: int = 5):
        self.query = query.strip()
        self.limit = limit
        self.items: List[Movie] = []

    @property
    def embed(self) -> Embed:
        embed = Embed(title=f"Query: `{self.query}`")

        for item in self.items:
            embed.add_field(name=item.title, value=item.markdown_url)

        return embed

    def search(self):
        item_list = self._db_command_to_dict("select * from movies where hidden=0")

        final_list = []
        for item in item_list:
            media_ = Movie(**item)
            title_ = media_.simple_title.lower()
            score = fuzz.ratio(self.query, title_)

            if score > 58:
                final_list.append(item)

        self.items.extend(
            [
                Movie(**item, _in_db=True)
                for item in sorted(final_list, key=itemgetter("score"), reverse=True)[
                    : self.limit
                ]
            ]
        )

        if not self.items:
            raise exceptions.NothingFound


class MediaFuzzySearch(Kinobase):
    media_types = (Movie, TVShow)

    def __init__(self, query: str, limit: int = 2):
        self.query = query.strip()
        self.limit = limit
        self.items: List[Union[Movie, TVShow]] = []

    @property
    def embed(self) -> Embed:
        embed = Embed(title=f"Query: `{self.query}`")

        for item in self.items:
            embed.add_field(name=item.title, value=item.markdown_url)

        return embed

    def search(self, table: str = "movies"):
        for media in self.media_types:

            if table not in media.table:
                continue

            item_list = self._db_command_to_dict(
                f"select * from {media.table} where hidden=0"
            )

            for item in item_list:
                media_ = media(**item)
                title_ = media_.simple_title.lower()
                score = fuzz.ratio(self.query, title_)

                if score > 58:
                    logger.debug("Score for %s: %d", media_.simple_title, score)

                    if score > 90:
                        self.items.insert(0, media_)
                    else:
                        self.items.append(media_)

        if not self.items:
            raise exceptions.NothingFound

        self.items = self.items[: self.limit]


class QuoteSearch:
    subs_path = SUBS_DIR

    def __init__(self, query: str, filter_: str = "", limit: int = 15):
        if len(query.strip()) < 4:
            raise exceptions.InvalidRequest(f"Too short query (<4): {query}")

        self.query = query.strip()
        self.pattern = self.query
        self.filter_ = filter_
        self.limit = limit
        self.media_items: List[Union[Movie, Episode]] = []
        self.items: List[dict] = []

    @property
    def embed(self) -> Embed:
        embed = Embed(title=f"Query: `{self.query}` (--filter `{self.filter_}`)")

        for quote, media in zip(self.items, self.media_items):
            logger.debug("Quote: %s; Media: %s", quote, media.title)
            embed.add_field(name=self._prettify(quote), value=media.markdown_url)

        embed.set_footer(text=f"Pattern: {self.pattern}")

        return embed

    def search(self):
        self._load_quotes()
        # Reversing the index will avoid losing indexes
        for index in reversed(range(len(self.items))):
            path = self.items[index]["basename"]
            logger.debug("Path: %s (%d index)", path, index)
            try:
                if is_episode(path):
                    media = Episode.from_subtitle_basename(path)
                else:
                    media = Movie.from_subtitle_basename(path)

                self.media_items.append(media)  # type: ignore

            # Ensure quotes and media results got the same range
            except exceptions.NothingFound:
                self.items.pop(index)

        # Reverse the list as we used a reversed index
        self.media_items.reverse()

        if not self.media_items or not self.items:
            raise exceptions.NothingFound

        assert len(self.media_items) == len(self.items)

    @staticmethod
    def _prettify(quote: dict):
        quote_ = quote["line"].replace("\n", " ")
        for submatch in quote["submatches"]:
            quote_ = quote_.replace(submatch, f"**{submatch}**")

        return quote_

    def _load_quotes(self):
        for found in self._gen_quote_results():
            if self.filter_ and self.filter_ not in found["filter"]:
                continue

            logger.debug("Appending quote: %s", found["line"].strip())
            self.items.append(found)

        shuffle(self.items)

        logger.debug("Using limit: %d", self.limit)
        self.items = self.items[: self.limit]

    def _get_rg_pattern(self) -> str:
        """
        Generate a punctuation-insensitive regex for ripgrep.
        """
        after_word = r"(\s|\W|$|(\W\s))"
        pattern = r"(^|\s|\W)"
        for word in self.query.split():
            word = re.sub(r"\W", "", word)
            pattern = pattern + word + after_word

        logger.debug("Generated pattern: %s", pattern)
        return pattern

    def _gen_quote_results(self) -> Generator[dict, None, None]:
        self.pattern = self._get_rg_pattern()

        rip_grep = Ripgrepy(self.pattern, self.subs_path)
        quote_list = rip_grep.i().json().run().as_dict  # type: ignore

        if len(quote_list) > 100:
            exceptions.InvalidRequest("Too common query")

        for quote in quote_list:
            path = quote["data"]["path"]["text"]
            if not path.endswith(".en.srt"):
                continue

            submatches = [sub["match"]["text"] for sub in quote["data"]["submatches"]]

            basename_ = os.path.basename(path)
            yield {
                "basename": basename_,
                "filter": basename_.lower().replace(".", " "),
                "line": quote["data"]["lines"]["text"],
                "submatches": submatches,
            }


class PersonSearch(Kinobase):
    def __init__(self, query: str, limit: int = 2, type_: str = "movies"):
        self.query = query.strip()
        self.limit = limit
        self.type_ = type_.title()
        self.items: List[Person] = []

    @property
    def embeds(self) -> List[Embed]:
        embeds = []

        for person in self.items:
            embed = Embed(title=person.name, url=person.web_url)
            items = [Movie(**item).markdown_url for item in person.get_movies()]
            if items:
                embed.add_field(name=self.type_, value=", ".join(items))
            else:
                embed.add_field(name=self.type_, value="Nothing found")
            embed.set_footer(text="Kinobot")
            embeds.append(embed)

        return embeds

    def search(self):
        results = self._db_command_to_dict(
            "select * from people where name like ? order by popularity desc limit ?",
            (f"%{self.query}%", self.limit),
        )
        if results:
            people = [Person(**item) for item in results]
            logger.debug("Appending: %d people", len(results))
            self.items.extend(people)
        else:
            raise exceptions.NothingFound


class MetadataSearch(Kinobase):
    item_cls = Genre

    def __init__(self, query: str, limit: int = 1):
        self.query = query.strip()
        self.limit = limit
        self.items: List[Genre] = []

    @cached_property
    def embed(self) -> Embed:
        item = self.items[0]

        movies = item.get_movies()
        items_len = len(movies)

        if items_len > 20:
            shuffle(movies)

        items = [Movie(**item).markdown_url for item in movies[:20]]

        embed = Embed(
            title=item.name,
            description=", ".join(items),
            url=item.web_url,
        )

        if items_len > 20:
            embed.set_footer(
                text=f"Showing 20 items out of {items_len}. Run the command"
                " again to see more."
            )

        return embed

    def search(self):
        results = self._db_command_to_dict(
            f"select * from {self.item_cls.table} where name like ? limit ?",
            (f"%{self.query}%", self.limit),
        )
        if results:
            items = [self.item_cls(**item) for item in results]
            self.items.extend(items)
        else:
            raise exceptions.NothingFound


class GenreSearch(MetadataSearch):
    pass


class CategorySearch(MetadataSearch):
    item_cls = Category


class CountrySearch(MetadataSearch):
    item_cls = Country


class RequestSearch(Kinobase):
    def __init__(self, query: str, limit: int = 10):
        self.query = query.strip()
        self.limit = limit
        self.items: List[Request] = []

    @property
    def embed(self) -> Embed:
        embed = Embed(title=f"Requests that contain `{self.query}`:")
        for req in self.items:
            embed.add_field(name=req.id, value=req.comment, inline=False)

        return embed

    def search(self):
        results = self._db_command_to_dict(
            "select * from requests where (type || '--' || comment) like ? "
            "and used=0 order by RANDOM() limit ?",
            (
                f"%{self.query}%",
                self.limit,
            ),
        )
        if results:
            self.items.extend([Request.from_sqlite_dict(item) for item in results])
        else:
            raise exceptions.NothingFound


class SongSearch(Kinobase):
    def __init__(self, query: str, limit: int = 5):
        self.query = query.strip()
        self.limit = limit
        self.items: List[Song] = []

    @property
    def embed(self) -> Embed:
        embed = Embed(title=f"Songs that contain `{self.query}`:")
        for song in self.items:
            embed.add_field(name=song.simple_title, value=song.path, inline=False)

        return embed

    def search(self):
        results = self._db_command_to_dict(
            "select * from songs where (artist || '--' || title ) like ? "
            "and hidden=0 order by RANDOM() limit ?",
            (
                f"%{self.query}%",
                self.limit,
            ),
        )
        if results:
            self.items.extend([Song(**item) for item in results])
        else:
            raise exceptions.NothingFound


@region.cache_on_arguments()
def _tmdb_find_movie(query: str, index: int = 0) -> Movie:
    match = _YEAR_RE.findall(query.strip())

    if not match or (len(query) == 4 and len(match) == 1):
        year = None
    else:
        query = " ".join(query.replace(match[-1], "").split())
        year = match[-1]

    logger.info("Searching movie: %s (%s)", query, year)
    search = tmdb.Search()
    search.movie(query=query, year=year)

    # tmdbsimple issue
    # pylint: disable=maybe-no-member
    if not search.results:  # type: ignore
        raise exceptions.NothingFound

    movies = sorted(
        search.results,  # type: ignore
        key=itemgetter("vote_count"),
        reverse=True,
    )

    return Movie.from_tmdb(movies[index])
