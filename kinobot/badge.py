#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import sqlite3
import time

from .constants import WEBSITE
from .db import Kinobase
from .media import Movie

logger = logging.getLogger(__name__)

# Scale of -30 to 15. It may change at any time.
WEIGHTS = {
    "catastrophic": -60,
    "atrocious": -30,
    "very_bad": -15,
    "bad": -7,
    "forgivable": -1,
    "regular": 1,
    "extra": 3,
    "good": 5,
    "very_good": 7,
    "incredibly_good": 9,
    "insane": 12,
    "never_happens": 15,
}


class Badge(Kinobase):
    """Base class for badges won after a request is posted on Facebook."""

    id = 0
    name = "name"
    description = "Unknown"
    _key = "regular"

    table = "badges"
    __insertables__ = ("id", "name", "weight")

    def __init__(self, **kwargs):
        self._reason = "Unknown"
        self._weight = None
        self.count = 0

        self._set_attrs_to_values(kwargs)

    @property
    def weight(self) -> int:
        if self._weight is None:
            return WEIGHTS[self._key]

        return self._weight

    @weight.setter
    def weight(self, val):
        self._weight = val

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def fb_reason(self) -> str:
        return f"🏆 {self.name.title()}: {self.reason}"

    @property
    def web_url(self) -> str:
        return f"{WEBSITE}/badge/{self.id}"

    @property
    def discord_tuple(self) -> tuple:
        return self.name.title(), self.count, self.points

    @property
    def points(self) -> int:
        return self.count * self.weight

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
        sql = "insert into user_badges (user_id, post_id, badge_id) values (?,?,?)"
        self._execute_sql(sql, (user_id, post_id, self.id))

    def insert(self):
        "Insert the badge in the database."
        insert = "insert into badges (id, name, weight) values (?,?,?)"
        update = "update badges set id=?,name=?,weight=? where id=?"
        params = [self.id, self.name, self.weight]

        try:
            self._execute_sql(insert, tuple(params))  # Type's sake
        except sqlite3.IntegrityError:
            params.append(self.id)
            self._execute_sql(update, tuple(params))

    @classmethod
    def update_all(cls):
        "Insert or update all the badges in the database."
        for badge in cls.__subclasses__():
            for sub_badge in badge.__subclasses__():
                bdg = sub_badge()
                bdg.insert()
                time.sleep(1)  # Avoid database locks

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


class ArbitraryBadge(Badge):
    "Base class for badges earned at admin/community criteria."

    def check(self) -> bool:
        return self is not None


class HandlerBadge(Badge):
    "Base class for badges computed from request handler data"
    type = "media"

    __max__ = {
        "contrast": (20, 7),  # 20 default
        "color": (0, 7),
        "brightness": (0, 7),
        "sharpness": (0, 7),
        "y_offset": (85, 5),
        "stroke_width": (3, 1),
        "text_spacing": (1, 1),
        "font_size": (27, 2),
    }

    def check(self, item) -> bool:
        return item is not None

    def _get_pretentious_count(self, item) -> int:
        count = 0
        for key, val in item.items():
            default_limit = self.__max__.get(key)
            if default_limit is None or default_limit[0] == val:
                continue

            default, limit = default_limit
            if abs(val - default) <= limit:
                logger.debug("Pretentious %s value found: %s", key, val)
                count += 1

        return count


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
    """Badge won when "cringe" is part of the categories of a movie."""

    id = 5
    name = "cringephile"
    _key = "forgivable"

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
    "Badge won when a movie has a popularity value no greater than 8."

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
    "Automatically won badge."

    id = 9
    name = "requester"
    _key = "regular"

    def __init__(self, **kwargs):
        super().__init__()

        self._reason = "The item got posted, but nothing else"
        self._set_attrs_to_values(kwargs)

    def check(self, media: Movie) -> bool:
        assert self and media
        return True


class Weeb(StaticBadge):
    "Badge won when a movie is animated and from Japan."

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
    "Badge won when a post gets more than 500 reactions."
    name = "gold owner"
    id = 11
    _key = "very_good"


class DiamondOwner(InteractionBadge):
    "Badge won when a post gets more than 1000 reactions."
    name = "diamond owner"
    id = 12
    threshold = 1000
    _key = "incredibly_good"


class Auteur(InteractionBadge):
    "Badge won when a post gets more than 2000 reactions."
    name = "auteur"
    id = 13
    threshold = 2000
    _key = "insane"


class GOAT(InteractionBadge):
    "Badge won when a post gets more than 3000 reactions."
    name = "goat"
    id = 14
    threshold = 3000
    _key = "never_happens"


class Socrates(InteractionBadge):
    "Badge won when a post gets more than 50 comments."
    name = "socrates"
    type = "comments"
    id = 15
    threshold = 50
    _key = "good"


class DrunkSocrates(InteractionBadge):
    "Badge won when a post gets more than 100 comments."
    name = "drunk socrates"
    type = "comments"
    id = 16
    threshold = 99
    _key = "incredibly_good"


class ReachKiller(InteractionBadge):
    "Badge won when a post gets less than 30 reacts."
    name = "reach killer"
    id = 17
    _key = "atrocious"

    @property
    def reason(self) -> str:
        assert self
        return "Dude just won a reach killer badge 😹💀"

    def check(self, amount: int) -> bool:
        assert self
        return amount < 50


class PalmedOrOwner(ArbitraryBadge):
    "Badge won when a post is among the greatests in bot's history."
    name = "Palme d'Or owner"
    id = 18
    _key = "never_happens"


class CertifiedLoyalMember(ArbitraryBadge):
    "Badge won when a member is known for being loyal."
    name = "certified loyal member"
    id = 19
    _key = "never_happens"


class TechnologicallyLiterate(HandlerBadge):
    """Badge won when a handler has more than 5 flags. This badge is cancelled
    if a pretentious badge is found."""

    name = "technologically literate"
    id = 20
    _key = "extra"

    def check(self, item) -> bool:
        return item is None


class PretentiousRequester(HandlerBadge):
    """Badge won when a set flag with a difference of ~5% or less closer
    to its default value is found."""

    name = "pretentious requester"
    id = 21
    _key = "bad"
    type = "postproc"

    def check(self, item):
        return self._get_pretentious_count(item) > 0


class IncrediblyPretentiousRequester(HandlerBadge):
    """Badge won when two or more set integer flags with a difference of ~5%
    or less closer to its default value is found."""

    name = "incredibly pretentious requester"
    id = 22
    type = "postproc"
    _key = "very_bad"

    def check(self, item):
        return self._get_pretentious_count(item) > 1


class MusicNerd(HandlerBadge):
    "Badge won when a music video is part of a parallel."
    name = "music nerd"
    id = 23
    type = "media"
    _key = "very_good"

    def check(self, items) -> bool:
        return any("song" == item for item in items)


class Dadaist(HandlerBadge):
    "Badge won when a Miscellaneous video is part of a parallel."
    name = "dadaist"
    id = 24
    _key = "good"

    def check(self, item) -> bool:
        return item is None


class ReachIlliterate(InteractionBadge):
    "Badge won when a post gets less than 100 reacts."
    name = "reach illiterate"
    id = 25
    _key = "very_bad"

    @property
    def reason(self) -> str:
        assert self
        return (
            "*They got a name for the winners in the world; "
            "I want a name when I lose* 🎶"
        )

    def check(self, amount: int) -> bool:
        assert self
        return amount < 100


class Mixtape(InteractionBadge):
    "Bage won when a post is shared more than 100 times."
    name = "mixtape"
    id = 26
    type = "shares"
    _key = "very_good"


class LilWayneMixtape(InteractionBadge):
    "Badge won when a post is shared more than 200 times."
    name = "lil wayne mixtape"
    id = 27
    type = "shares"
    threshold = 200
    _key = "incredibly_good"


class SharesAuteur(InteractionBadge):
    "Badge won when a post is shared more than 500 times."
    name = "shares auteur"
    id = 28
    type = "shares"
    threshold = 500
    _key = "insane"


class SharesGoat(InteractionBadge):
    "Badge won when a post is shared more than 750 times."
    name = "shares GOAT"
    id = 29
    type = "shares"
    threshold = 750
    _key = "never_happens"


class AttentionWhore(InteractionBadge):
    "Badge won when a post is clicked more than 1000 times."
    name = "attention whore"
    id = 30
    type = "clicks"
    threshold = 1000
    _key = "extra"


class AuteurAttentionWhore(InteractionBadge):
    "Badge won when a post is clicked more than 2000 times."
    name = "auteur attention whore"
    id = 31
    type = "clicks"
    threshold = 2000
    _key = "good"


class GoatAttentionWhore(InteractionBadge):
    "Badge won when a post is clicked more than 4000 times."
    name = "goat attention whore"
    id = 32
    type = "clicks"
    threshold = 4000
    _key = "very_good"


class Scrutinized(InteractionBadge):
    "Badge won when a post has more than 10k views."
    name = "scrutinized"
    id = 33
    type = "views"
    threshold = 10000
    _key = "good"


class HeavilyScrutinized(InteractionBadge):
    "Badge won when a post has more than 20k views."
    name = "heavily scrutinized"
    id = 34
    type = "views"
    threshold = 20000
    _key = "very_good"


class ReachIlliterateAntithesis(InteractionBadge):
    "Badge won when a post has more than 30k views."
    name = "reach illiterate antithesis"
    id = 35
    type = "views"
    threshold = 30000
    _key = "incredibly_good"


class ReachKillerAntithesis(InteractionBadge):
    "Badge won when a post has more than 50k views."
    name = "reach killer antithesis"
    id = 36
    type = "views"
    threshold = 50000
    _key = "never_happens"


class Artist(HandlerBadge):
    """Badge won when both `--border` and `--text-background` flags are
    found in a parallel. Note that the border must be of a size greater
    than 3."""

    name = "artist"
    id = 37
    type = "postproc"
    _key = "insane"

    def check(self, item) -> bool:
        if isinstance(item["border"], tuple):
            logger.debug("Found border: %s", item["border"])
            text = item["text_background"] is not None
            border = item["border"][0] > 3 or item["border"][1] > 3
            return border and text

        return False


class Patrician(HandlerBadge):
    """Badge won when an album cover art is found in a parallel request.
    These parallels are very rare, hard to make them look good and,
    consequently, unlikely to get verified."""

    name = "patrician"
    id = 38
    type = "media"
    _key = "very_good"

    def check(self, items) -> bool:
        return any("cover" == item for item in items)


class ArtHistorician(HandlerBadge):
    """Badge won when an artwork is found in a parallel request.
    These parallels are very rare, hard to make them look good and,
    consequently, unlikely to get verified."""

    name = "art historician"
    id = 39
    type = "media"
    _key = "insane"

    def check(self, items) -> bool:
        return any("artwork" == item for item in items)


class InsanelyPretentiousRequester(HandlerBadge):
    """Badge won when three or more set integer flags with a difference of ~5%
    or less closer to its default value is found."""

    name = "ridiculously pretentious requester"
    id = 40
    type = "postproc"
    _key = "atrocious"

    def check(self, item):
        return self._get_pretentious_count(item) > 2


class ReachGenocide(InteractionBadge):
    "Badge won when a post gets less than 25 reacts."
    name = "reach genocide"
    id = 41
    _key = "catastrophic"

    def check(self, amount: int) -> bool:
        assert self
        return amount < 25


class ReachNovice(InteractionBadge):
    "Badge won when a post gets less than 150 reacts."
    name = "reach novice"
    id = 42
    _key = "bad"

    def check(self, amount: int) -> bool:
        assert self
        return amount < 150


class Rejected(ArbitraryBadge):
    """Badge won when a request gets rejected. As the request can't
    be posted, this badge is associated with the request ID."""

    name = "rejected"
    id = 43
    _key = "forgivable"


class Punished(ArbitraryBadge):
    """Arbitrary badge won when an user threatens Kinobot's integrity."""

    name = "punished"
    id = 44
    _key = "punished"
    _weight = -500

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._weight = -500
