import logging
import os
import random
import re
import sqlite3

import kinobot.exceptions as exceptions
from kinobot.db import get_list_of_movie_dicts
from kinobot.request import get_subtitle, search_movie

KINOBASE = os.environ.get("KINOBASE")
MOVIES = get_list_of_movie_dicts()

logger = logging.getLogger(__name__)


def search_items(column, query):
    """
    :param column: column (director, country, year)
    :param query: query
    """
    if len(str(query)) < 4:
        return []
    with sqlite3.connect(KINOBASE) as conn:
        query = "%" + str(query) + "%"
        movies = conn.execute(
            "select title, year, country from movies where {} like ?".format(column),
            (query,),
        ).fetchall()
        # filter movies with a lot of countries
        if column == "country":
            movies = [i for i in movies if len(i[2].split(", ")) < 6]
        return movies


def find_quote(subtitle_list, keywords):
    """
    :param subtitle_list: list of subtitle objects from srt
    :param keywords: list of keywords
    """
    contents = [sub.content for sub in subtitle_list]
    quotes = []
    for i in contents:
        if any(
            " " + keyword.lower() in i.lower() or keyword.lower() + " " in i.lower()
            for keyword in keywords
        ):
            quotes.append(i)
    if quotes:
        return random.choice(quotes)


def discover_movie(query, db_key, keywords):
    """
    Find a movie quote from common info (country, year or director).

    :param query: query
    :param db_key: country, year or director
    :param keywords: space-separated keywords
    :raises exceptions.BadKeywords
    :raises exceptions.TooShortQuery
    :raises exceptions.MovieNotFound
    :raises exceptions.QuoteNotFound
    """
    if re.match("^[A-Z][^?!.,]*[?.!,]$", keywords):
        raise exceptions.BadKeywords
    if len(keywords) < 4:
        raise exceptions.TooShortQuery

    keywords = keywords.split(" ")
    results = search_items(db_key, query)

    if not results:
        raise exceptions.MovieNotFound

    final_list = []
    for result in results:
        found_movie = search_movie(MOVIES, result[0] + " " + str(result[1]))
        try:
            subtitles = get_subtitle(found_movie)
        except FileNotFoundError:
            continue
        quote = find_quote(subtitles, keywords)
        if quote:
            final_list.append(
                {
                    "title": found_movie["title"],
                    "year": found_movie["year"],
                    "quote": quote,
                }
            )
    if final_list:
        final_result = random.choice(final_list)
        logger.info("Quote found:")
        logger.info(final_result)
        return final_result
    raise exceptions.QuoteNotFound
