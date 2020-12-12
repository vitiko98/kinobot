import logging
import os
import random
import re
import sqlite3
import sys

import utils.db_client as db_client
import utils.kino_exceptions as kino_exceptions
import utils.subs as subs

KINOBASE = os.environ.get("KINOBASE")
MOVIES = db_client.get_complete_list()

logger = logging.getLogger(__name__)


def search_item(column, query):  # year, country, director
    logger.info("Looking for quotes...")
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
    if re.match("^[A-Z][^?!.,]*[?.!,]$", keywords):
        raise kino_exceptions.BadKeywords
    if len(keywords) < 4:
        raise kino_exceptions.TooShortQuery

    keywords = keywords.split(" ")
    results = search_item(db_key, query)

    if not results:
        kino_exceptions.NotEnoughSearchScore

    final_list = []
    for result in results:
        found_movie = subs.search_movie(
            MOVIES, result[0] + " " + str(result[1]), log_score=False
        )
        try:
            subtitles = subs.get_subtitle(found_movie)
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
    raise kino_exceptions.NotEnoughSearchScore
