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
    weight = 10

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

    def register(self, user_id: str, post_id: str):
        """Register the badge for a post and its user.

        :param user_id:
        :type user_id: str
        :param post_id:
        :type post_id: str
        :raises sqlite3.IntegrityError
        """
        if self.reason != "Unknown":
            sql = "insert into user_badges (user_id, post_id, badge_id) values (?,?,?)"
            self._execute_sql(sql, (user_id, post_id, self.id))

    def __repr__(self) -> str:
        return f"<Badge {self.name}>"


class StaticBadge(Badge):
    """Base class for badges computed from media metadata (movies and
    episodes). This class can also compute any data from the Static handler."""

    def check(self, media: Movie) -> bool:
        assert self and media
        return True


class InteractionBadge(Badge):
    """Base class for badges computed from Facebook metadata (reactions,
    comments, etc)."""

    threshold = 500  # amount of reactions, comments, etc.
    type = "reacts"

    @property
    def reason(self) -> str:
        return f"More than {self.threshold} {self.type} met"

    def check(self, amount: int) -> bool:
        assert self
        met = amount > self.threshold
        # Debug, debug!
        logger.debug("%s meet? %s: %d %s", self.name, met, amount, self.type)
        return met


class Feminist(StaticBadge):
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
            self._reason = "More than 5 women are part of the movie"
            logger.info("Reason found: %s (%s)", self._reason, women)
            return True

        return False


class Historician(StaticBadge):
    "Badge won when a movie is produced before 1940."
    id = 2
    name = "historician"

    def check(self, media: Movie) -> bool:
        if media.year is not None and int(media.year) < 1940:
            self._reason = f"The movie was produced before 1940: {media.year}"
            logger.info("Reason found: %s", self._reason)
            return True

        return False


class Republican(StaticBadge):
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


class NonBinary(StaticBadge):
    """Badge won when a person without genre (according to TMDB) is found in a
    movie."""

    id = 4
    name = "nonbinary"

    def check(self, media: Movie) -> bool:
        people = media.metadata.credits.people
        items = [person.name for person in people if person.gender == "0"]

        if not items:
            return False

        if len(items) > 3:
            self._reason = (
                f"{len(items)} people without registered gender are part of the movie"
            )
            logger.info("Reason found: %s", self._reason)
            return True

        return False


class Cringephile(StaticBadge):
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


class Comrade(StaticBadge):
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

        self._reason = f"Countries found in the movie: {', '.join(items)}"
        logger.info("Reason found: %s", self._reason)

        return True


class Hustler(StaticBadge):
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


class Explorer(StaticBadge):
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
            f"African or Oceanic countries found in the movie: {', '.join(items)}"
        )
        logger.info("Reason found: %s", self._reason)

        return True


class Requester(StaticBadge):
    " Automatically won badge. "

    id = 9
    name = "requester"
    weight = 5

    def __init__(self, **kwargs):
        super().__init__()

        self._reason = "The item got posted, but nothing else"
        self._set_attrs_to_values(kwargs)

    def check(self, media: Movie) -> bool:
        assert self and media
        return True


class Weeb(StaticBadge):
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


class GoldOwner(InteractionBadge):
    " Badge won when a post gets more than 500 reactions. "
    name = "gold owner"
    id = 11
    weight = 20


class DiamondOwner(InteractionBadge):
    " Badge won when a post gets more than 1000 reactions. "
    name = "diamond owner"
    id = 12
    threshold = 1000
    weight = 25


class Auteur(InteractionBadge):
    " Badge won when a post gets more than 2000 reactions. "
    name = "auteur"
    id = 13
    threshold = 2000
    weight = 30


class GOAT(InteractionBadge):
    " Badge won when a post gets more than 3000 reactions. "
    name = "goat"
    id = 14
    threshold = 3000
    weight = 100


class Socrates(InteractionBadge):
    " Badge won when a post gets more than 50 comments. "
    name = "socrates"
    type = "comments"
    id = 15
    threshold = 50
    weight = 20


class DrunkSocrates(InteractionBadge):
    " Badge won when a post gets more than 100 comments. "
    name = "drunk socrates"
    type = "comments"
    id = 16
    threshold = 100
    weight = 40


class ReachKiller(InteractionBadge):
    " Badge won when a post gets less than 30 reacts. "
    name = "reach killer"
    id = 17
    weight = -10

    @property
    def reason(self) -> str:
        assert self
        return "Dude just won a reach killer badge 😹💀"

    def check(self, amount: int) -> bool:
        assert self
        return amount < 30
