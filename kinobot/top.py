#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
from operator import itemgetter
from typing import List, Optional

import numpy as np

from .cache import TOP_TIME, region
from .db import Kinobase
from .exceptions import InvalidRequest, NothingFound
from .media import Movie
from .user import User

logger = logging.getLogger(__name__)


class TopMovies(Kinobase):
    "Class for Top 250 rated Kinobot's movies."

    def __init__(self, limit: int = 500, minimum_votes: int = 1):
        self.limit = limit
        self.minimum_votes = minimum_votes
        self.items: List[Movie] = []
        self._loaded = False

    def load(self):
        self._loaded = True
        for item in self._get_sorted("cached"):
            movie = Movie(**item)
            movie.metadata.position = item["position"]
            self.items.append(movie)

    def discord(self, from_to: tuple = (0, 9)) -> str:
        """Generate a top string suitable for Discord.

        :param from_to:
        :type from_to: tuple
        :rtype: str
        :raises:
            exceptions.InvalidRequest
            exceptions.NothingFound
        """
        from_, to_ = from_to

        if abs(from_ - to_) > 11:
            raise InvalidRequest("11 range limit exceded")

        if from_ > to_:
            raise InvalidRequest("Invalid range")

        if not self._loaded:
            self.load()

        tmp_list = self.items[from_:][: to_ - from_]

        if not tmp_list:
            raise NothingFound

        note = "`The top is updated every hour`"
        top_str = "\n".join(item.top_title for item in tmp_list)

        return "\n\n".join((top_str, note))

    def get_position(self, item_id) -> Optional[int]:
        """Get the position of a movie in the top.

        :param item_id:
        :type item_id: int
        :rtype: Optional[int]
        """
        item_id = str(item_id)
        for item in self._get_sorted("cached"):
            if item["id"] == item_id:
                return item["position"]

        return None

    @region.cache_on_arguments(expiration_time=TOP_TIME)
    def _get_sorted(self, cache: str) -> List[dict]:
        """Compute the top list of movies. Use dictionaries top allow caching.

        :param cache:
        :type cache: str
        :rtype: List[dict]
        """
        assert cache is not None
        sql = (
            "SELECT movies.*, avg(movie_ratings.rating) as avg, count(*) as "
            "count from movie_ratings inner join movies on movie_ratings."
            "rated_movie=movies.id group by rated_movie"
        )
        items = self._db_command_to_dict(sql)
        mean_avg = np.mean([item["avg"] for item in items])

        for item in items:
            average, votes = item["avg"], item["count"]
            result = (votes / (votes + self.minimum_votes)) * average + (
                self.minimum_votes / (votes + self.minimum_votes)
            ) * mean_avg
            item["weighted_rating"] = float(result)

        logger.info("Sorting %d items", len(items))

        new_list = sorted(items, key=itemgetter("weighted_rating"), reverse=True)

        for position, item in enumerate(new_list, 1):
            item.update({"position": position})

        return new_list
