#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging

from .constants import WEBSITE
from .db import Kinobase
from .media import Movie

logger = logging.getLogger(__name__)


class Badge(Kinobase):
    """Base class for badges won after a request is posted on Facebook."""

    id = 0
    name = "name"

    def __init__(self, **kwargs):
        self._reason = "Unknown"

        self._set_attrs_to_values(kwargs)

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def fb_reason(self) -> str:
        return f"🏆 {self.name.title()}: {self.reason}"

    @property
    def web_url(self) -> str:
        return f"{WEBSITE}/badge/{self.name}"

    @property
    def markdown_url(self) -> str:
        return f"[{self.web_url}]({self.name.title()})"

    def check(self, media: Movie) -> bool:
        assert self and media
        return True

    def register(self, user_id: str, post_id: str):
        if self._reason != "Unknown":
            sql = (
                "insert or ignore into user_badges (user_id, post_id, "
                "badge_id) values (?,?,?)"
            )
            self._execute_sql(sql, (user_id, post_id, self.id))

    def __repr__(self) -> str:
        return f"<Badge {self.name}>"


class Feminist(Badge):
    """Badge won when more than five women are found in a movie or the
    director is a woman."""

    id = 1
    name = "feminist"

    def check(self, media: Movie) -> bool:
        directors = media.metadata.credits.directors

        if any(item.gender == "1" for item in directors):
            self._reason = (
                "A woman is the director of the movie: "
                f"{', '.join(item.name for item in directors)}"
            )
            logger.info("Reason found: %s", self._reason)
            return True

        people = media.metadata.credits.people
        if not people:
            return False

        women = [person for person in people if person.gender == "1"]
        if len(women) > 5:
            self._reason = "More than 5 women are part of the movie."
            logger.info("Reason found: %s (%s)", self._reason, women)
            return True

        return False


class Historician(Badge):
    "Badge won when a movie is produced before 1940."
    id = 2
    name = "historician"

    def check(self, media: Movie) -> bool:
        if media.year is not None and int(media.year) < 1940:
            self._reason = f"The movie was produced before 1940: {media.year}"
            logger.info("Reason found: %s", self._reason)
            return True

        return False


class Republican(Badge):
    "Badge won when a known conservative (e.g. John Wayne) is found in a movie."

    id = 3
    name = "republican"
    __tokens = ("John Wayne", "Clint Eastwood")  # TODO: add more

    def check(self, media: Movie) -> bool:
        people = media.metadata.credits.people
        items = [person.name for person in people if person.name in self.__tokens]

        if not items:
            return False

        self._reason = (
            f"Known conservative people are part of the movie: {', '.join(items)}"
        )
        logger.info("Reason found: %s", self._reason)
        return True


class NonBinary(Badge):
    """Badge won when a person without genre (according to TMDB) is found in a
    movie."""

    id = 4
    name = "nonbinary"

    def check(self, media: Movie) -> bool:
        people = media.metadata.credits.people
        items = [person.name for person in people if person.gender == "0"]

        if not items:
            return False

        if len(items) > 2:
            self._reason = (
                f"{len(items)} people without registered genre are part of "
                "the movie."
            )
            logger.info("Reason found: %s", self._reason)
            return True

        return False


class Cringephile(Badge):
    """ Badge won when "cringe" is part of the categories of a movie. """

    id = 5
    name = "cringephile"

    def check(self, media: Movie) -> bool:
        cats = media.metadata.categories
        if not cats:
            return False

        if any("cringe" in cat.name.lower() for cat in cats):
            self._reason = "The movie has a cringe category"
            logger.info("Reason found: %s (%s)", self._reason, cats)
            return True

        return False


class Comrade(Badge):
    """Badge won when Soviet Union or Cuba are part of the production countries
    of a movie."""

    id = 6
    name = "comrade"
    __tokens = ("Soviet Union", "Cuba", "China")  # inb4: China is not communist

    def check(self, media: Movie) -> bool:
        countries = media.metadata.countries
        logger.debug("Countries: %s", countries)
        items = [item.name for item in countries if item.name in self.__tokens]

        if not items:
            return False

        self._reason = f"Countries found in the movie: {'. '.join(items)}"
        logger.info("Reason found: %s", self._reason)

        return True


class Hustler(Badge):
    " Badge won when a movie has a popularity value no greater than 8. "

    id = 7
    name = "hustler"

    def check(self, media: Movie) -> bool:
        if media.popularity is not None and (media.popularity < 8):
            self._reason = (
                f"The movie is not widely popular ({media.popularity} points)"
            )
            logger.info("Reason found: %s", self._reason)
            return True

        return False


class Explorer(Badge):
    """Badge won when an african or oceanic country is part of the production
    countries of a movie."""

    id = 8
    name = "explorer"
    __tokens = ("DZ", "GH", "ZA", "AU", "NZ", "EG")  # TODO: add all countries

    def check(self, media: Movie) -> bool:
        items = []
        # Loop used to exactly match country codes
        for country in media.metadata.countries:
            if any(code == country.id for code in self.__tokens):
                logger.info("Country found: %s", country)
                items.append(country.name)

        if not items:
            return False

        self._reason = (
            f"African or Oceanic countries found in the movie: {'. '.join(items)}"
        )
        logger.info("Reason found: %s", self._reason)

        return True


class Requester(Badge):
    " Automatically won badge. "

    id = 9
    name = "requester"

    def __init__(self, **kwargs):
        super().__init__()

        self._reason = "The item got posted, but nothing else"
        self._set_attrs_to_values(kwargs)

    def check(self, media: Movie) -> bool:
        assert self and media
        return True


class Weeb(Badge):
    " Badge won when a movie is animated and from Japan. "

    id = 10
    name = "weeb"

    def check(self, media: Movie) -> bool:
        countries = media.metadata.countries
        genres = media.metadata.genres

        if "Japan" in countries and "Animation" in genres:
            self._reason = "The movie is animated and from Japan."
            logger.info("Reason found: %s", self._reason)
            return True

        return False
