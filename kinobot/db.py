#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import os
import sqlite3
import time
from operator import itemgetter
from pathlib import Path

import click
import requests
import tmdbsimple as tmdb

import kinobot.exceptions as exceptions
from kinobot.config import KINOBASE, RADARR, RADARR_URL, REQUESTS_DB, TMDB

IMAGE_BASE = "https://image.tmdb.org/t/p/original"
tmdb.API_KEY = TMDB


logger = logging.getLogger(__name__)


def create_db_tables():
    with sqlite3.connect(KINOBASE) as conn:
        try:
            conn.execute(
                """
                CREATE TABLE MOVIES (title TEXT NOT NULL, og_title TEXT,
                year INT, director TEXT, country TEXT, category TEXT, poster
                TEXT, backdrop TEXT, path TEXT NOT NULL, subtitle TEXT, tmdb
                TEXT NOT NULL, overview TEXT, popularity TEXT, budget TEXT,
                source TEXT, imdb TEXT, runtime TEXT, requests INT,
                last_request INT DEFAULT (0));
                """
            )
            logger.info("Table created: MOVIES")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute(
                """CREATE TABLE USERS (name TEXT UNIQUE, requests INT
                DEFAULT (0), warnings INT DEFAULT (0), digs INT DEFAULT (0),
                indie INT DEFAULT (0), historician INT DEFAULT (0),
                animation INT DEFAULT (0), blocked BOOLEAN DEFAULT (0));"""
            )
            logger.info("Table created: USERS")
        except sqlite3.OperationalError:
            pass

        conn.commit()


def insert_into_table(values):
    """
    :param values: tuple from insert_movie
    """
    with sqlite3.connect(KINOBASE) as conn:
        sql = """INSERT INTO MOVIES
        (title, og_title, year, director, country, category,
        poster, backdrop, path, subtitle, tmdb, overview,
        popularity, budget, source, imdb, runtime, requests)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)"""
        cur = conn.cursor()
        try:
            cur.execute(sql, values)
        except sqlite3.IntegrityError:
            logger.info(
                f"{values[0]} ({values[8]}) has been detected as "
                "a duplicate title. Do something about it!"
            )
        finally:
            conn.commit()


def insert_movie(movie_dict):
    """
    :param movie_dict: Movie dictionary from Radarr
    """
    # pylint: disable=E1101
    i = movie_dict

    filename = i["movieFile"]["path"]
    to_srt = Path(filename).with_suffix("")
    srt = f"{to_srt}.en.srt"

    logger.info("Getting movie info from TheMovieDatabase.org")
    movie = tmdb.Movies(i["tmdbId"])
    movie.info()
    country_list = ", ".join([i["name"] for i in movie.production_countries])
    movie.credits()
    dirs = [m["name"] for m in movie.crew if m["job"] == "Director"]
    logger.info("Ok")

    values = (
        movie.title,
        getattr(movie, "original_title", movie.title),
        movie.release_date.split("-")[0],
        ", ".join(dirs),
        country_list,
        input("Category:\n- ") or "Certified Kino",
        IMAGE_BASE + getattr(movie, "poster_path", "Unknown"),
        IMAGE_BASE + getattr(movie, "backdrop_path", "Unknown"),
        filename,
        srt,
        i["tmdbId"],
        i["overview"],
        movie.popularity,
        movie.budget,
        i["movieFile"]["quality"]["quality"]["name"].split("-")[0],
        i["imdbId"],
        i["movieFile"]["mediaInfo"]["runTime"],
    )

    insert_into_table(values)

    logger.info(f"Added: {movie.title}")


def get_radarr_list():
    " Fetch list from Radarr server. "
    logger.info("Retrieving movie list from Radarr")
    url = f"{RADARR_URL}/api/v3/movie?apiKey={RADARR}"
    response = requests.get(url)
    response.raise_for_status()
    return [i for i in json.loads(response.content) if i.get("hasFile")]


def reset_paths():
    with sqlite3.connect(KINOBASE) as conn:
        cursor = conn.execute("SELECT path from MOVIES")
        logger.info("Cleaning paths")
        for i in cursor:
            conn.execute("UPDATE MOVIES SET path='' WHERE path=?", (i))
        conn.commit()
        logger.info("Ok")


def force_update(radarr_list):
    """
    :param radarr_list: Radarr dictionary from get_radarr_list
    """
    with sqlite3.connect(KINOBASE) as conn:
        for i in radarr_list:
            imdb = i.get("imdbId", "Unknown")
            conn.execute(
                "UPDATE MOVIES SET source=?, imdb=?, runtime=? WHERE tmdb=?",
                (
                    i["movieFile"]["quality"]["quality"]["name"].split("-")[0],
                    (imdb),
                    (i["movieFile"]["mediaInfo"]["runTime"]),
                    (i["tmdbId"]),
                ),
            )
        conn.commit()


def update_paths(radarr_list):
    """
    :param radarr_list: Radarr dictionary from get_radarr_list
    """
    logger.info("Updating paths")
    with sqlite3.connect(KINOBASE) as conn:
        for i in radarr_list:
            conn.execute(
                "UPDATE MOVIES SET path=? WHERE title=?",
                ((i["movieFile"]["path"]), i["title"]),
            )
        conn.commit()
    logger.info("Ok")


def check_missing_movies(radarr_list):
    """
    :param radarr_list: Radarr dictionary from get_radarr_list
    """
    logger.info("Checking missing movies")
    with sqlite3.connect(KINOBASE) as conn:
        indexed_titles_db = [
            title[0] for title in conn.execute("SELECT title from MOVIES")
        ]
        count = 0
        for movie in radarr_list:
            if not any(i == movie["title"] for i in indexed_titles_db):
                logger.info(f"Adding {movie['title']}")
                count += 1
                insert_movie(movie)
        if count == 0:
            logger.info("No missing movies")


def get_requests():
    with sqlite3.connect(REQUESTS_DB) as conn:
        result = conn.execute("select * from requests where used=0").fetchall()
        return [
            {
                "user": i[0],
                "comment": i[1],
                "type": i[2],
                "movie": i[3],
                "content": i[4].split("|"),
                "id": i[5],
            }
            for i in result
        ]


def block_user(user, check=False):
    """
    :param user: Facebook name
    :param check: raise and exception if the user is blocked
    :raises exceptions.BlockedUser
    """
    with sqlite3.connect(os.environ.get("KINOBASE")) as conn:
        try:
            logger.info(f"Adding user: {user}")
            conn.execute("INSERT INTO USERS (name) VALUES (?)", (user,))
        except sqlite3.IntegrityError:
            logger.info("Already added")
        if check:
            if conn.execute(
                "select blocked from users where name=?", (user,)
            ).fetchone()[0]:
                raise exceptions.BlockedUser
            return
        logger.info(f"Blocking user: {user}")
        conn.execute("UPDATE USERS SET blocked=1 WHERE name=?", (user,))
        conn.commit()


def insert_request_info_to_db(movie, user):
    """
    :param movie: movie title from dictionary
    :param user: Facebook name
    """
    with sqlite3.connect(os.environ.get("KINOBASE")) as conn:
        logger.info(f"Updating requests count for movie {movie['title']}")
        conn.execute(
            "UPDATE MOVIES SET requests=requests+1 WHERE title=?", (movie["title"],)
        )
        logger.info(f"Updating last_request timestamp for movie {movie['title']}")
        timestamp = int(time.time())
        conn.execute(
            "UPDATE MOVIES SET last_request=? WHERE title=?",
            (
                timestamp,
                movie["title"],
            ),
        )
        try:
            logger.info(f"Adding user: {user}")
            conn.execute("INSERT INTO USERS (name) VALUES (?)", (user,))
        except sqlite3.IntegrityError:
            logger.info("Already added")
        logger.info("Updating requests count")
        conn.execute("UPDATE USERS SET requests=requests+1 WHERE name=?", (user,))
        if movie["popularity"] <= 9:
            logger.info(f"Updating digs count ({movie['popularity']})")
            conn.execute("UPDATE USERS SET digs=digs+1 WHERE name=?", (user,))
        if movie["budget"] <= 750000:
            logger.info(f"Updating indie count ({movie['budget']})")
            conn.execute("UPDATE USERS SET indie=indie+1 WHERE name=?", (user,))
        if movie["year"] < 1940:
            logger.info(f"Updating historician count ({movie['year']})")
            conn.execute(
                "UPDATE USERS SET historician=historician+1 WHERE name=?", (user,)
            )
        conn.commit()


def update_request_to_used(request_id):
    """
    :param request_id: request_id from DB or Facebook comment
    """
    with sqlite3.connect(REQUESTS_DB) as conn:
        logger.info("Updating request as used...")
        conn.execute(
            "update requests set used=1 where id=?",
            (request_id,),
        )
        conn.commit()


def get_list_of_movie_dicts():
    """
    Convert "MOVIES" table from DB to a list of dictionaries.
    """
    with sqlite3.connect(KINOBASE) as conn:
        cursor = conn.execute("SELECT * from MOVIES").fetchall()
        dict_list = []
        for i in cursor:
            if i[5] == "Blacklist" or not i[8]:
                continue
            to_srt = Path(i[8]).with_suffix("")
            srt = "{}.{}".format(to_srt, "en.srt")
            srt_split = srt.split("/")
            srt_relative_path = os.path.join(srt_split[-2], srt_split[-1])
            dict_list.append(
                {
                    "title": i[0],
                    "original_title": i[1],
                    "year": i[2],
                    "director": i[3],
                    "country": i[4],
                    "category": i[5],
                    "poster": i[6],
                    "backdrop": i[7],
                    "path": i[8],
                    "subtitle": srt,
                    "subtitle_relative": srt_relative_path,
                    "tmdb": i[10],
                    "overview": i[11],
                    "popularity": float(i[12]),
                    "budget": int(i[13]),
                    "source": i[14],
                    "runtime": i[16],
                    "requests": i[17],
                    "last_request": i[18],
                }
            )
        return sorted(dict_list, key=itemgetter("title"))


@click.command("library")
def update_library():
    " Update movie database from Radarr server. "
    logger.info("Updating Kinobot's database")
    create_db_tables()
    radarr_list = get_radarr_list()
    check_missing_movies(radarr_list)
    reset_paths()
    force_update(radarr_list)
    update_paths(radarr_list)
