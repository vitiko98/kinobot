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

from guessit import guessit
from plexapi.server import PlexServer
import click
import requests
import tmdbsimple as tmdb

import kinobot.exceptions as exceptions
from kinobot.utils import kino_log
from kinobot import (
    KINOBASE,
    EPISODE_COLLECTION,
    RADARR,
    RADARR_URL,
    REQUESTS_DB,
    TMDB,
    KINOLOG,
    PLEX_URL,
    PLEX_TOKEN,
)

IMAGE_BASE = "https://image.tmdb.org/t/p/original"
tmdb.API_KEY = TMDB


logger = logging.getLogger(__name__)

logger.warning(f"Using databases: {KINOBASE}, {REQUESTS_DB}")


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
                """
                CREATE TABLE EPISODES (title TEXT NOT NULL, season INT,
                episode INT, writer TEXT, category TEXT, path TEXT,
                subtitle TEXT, source TEXT, id INT UNIQUE, overview TEXT,
                requests INT DEFAULT (0), last_request INT DEFAULT (0));
                """
            )
            logger.info("Table created: EPISODES")

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
                "verified": i[7],
            }
            for i in result
        ]


def block_user(user, check=False):
    """
    :param user: Facebook name
    :param check: raise and exception if the user is blocked
    :raises exceptions.BlockedUser
    """
    with sqlite3.connect(KINOBASE) as conn:
        try:
            conn.execute("INSERT INTO USERS (name) VALUES (?)", (user,))
            logger.info(f"New user registered: {user}")
        except sqlite3.IntegrityError:
            pass
        if check:
            if conn.execute(
                "select blocked from users where name=?", (user,)
            ).fetchone()[0]:
                raise exceptions.BlockedUser
            return
        logger.info(f"Blocking user: {user}")
        conn.execute("UPDATE USERS SET blocked=1 WHERE name=?", (user,))
        conn.commit()


def verify_request(request_id):
    logger.info(f"Verifying request: {request_id}")
    with sqlite3.connect(REQUESTS_DB) as conn:
        conn.execute(
            "UPDATE requests SET verified=1, used=0 where id=?",
            (request_id,),
        )
        conn.commit()


def insert_episode_request_info_to_db(episode, user):
    with sqlite3.connect(KINOBASE) as conn:
        episode_title = f"{episode['title']} - {episode['season']} {episode['episode']}"
        logger.info(f"Updating requests count for episode {episode_title}")
        conn.execute(
            "UPDATE EPISODES SET requests=requests+1 WHERE id=?", (episode["id"],)
        )
        logger.info(
            f"Updating last_request timestamp for episode {episode_title} ({KINOBASE})"
        )
        timestamp = int(time.time())
        conn.execute(
            "UPDATE EPISODES SET last_request=? WHERE id=?",
            (
                timestamp,
                episode["id"],
            ),
        )
        conn.execute("UPDATE USERS SET requests=requests+1 WHERE name=?", (user,))
        conn.commit()


def insert_request_info_to_db(movie, user):
    """
    :param movie: movie title from dictionary
    :param user: Facebook name
    """
    with sqlite3.connect(KINOBASE) as conn:
        logger.info(f"Updating requests count for movie {movie['title']}")
        conn.execute(
            "UPDATE MOVIES SET requests=requests+1 WHERE title=?", (movie["title"],)
        )
        logger.info(
            f"Updating last_request timestamp for movie {movie['title']} ({KINOBASE})"
        )
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


def get_episodes():
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)

    logger.info("Retrieving data from Plex")
    shows = plex.library.section("TV Shows")
    episodes = shows.search(libtype="episode")

    episode_tuples = []
    for episode in episodes:
        path = episode.media[0].parts[0].file
        source = guessit(path).get("source", "N/A")
        srt_file = os.path.splitext(path)[0] + ".en.srt"
        writer = ", ".join([writer.tag for writer in episode.writers]) or "N/A"

        episode_tuples.append(
            (
                episode.grandparentTitle,
                writer,
                int(episode.parentTitle.split(" ")[1]),
                episode.index,
                "Hidden",
                path,
                srt_file,
                source,
                int(
                    episode.guid.split("://")[-1]
                    .replace("?lang=en", "")
                    .replace("/", "")
                ),
                episode.summary,
            )
        )

    return episode_tuples


def update_episode_table(episode_list):
    with sqlite3.connect(KINOBASE) as conn:
        logger.info("Updating episode paths")
        for episode in episode_list:
            conn.execute(
                "UPDATE EPISODES SET path=? WHERE id=?",
                (
                    episode[5],
                    episode[8],
                ),
            )

        sql = """INSERT INTO EPISODES
        (title, writer, season, episode, category,
        path, subtitle, source, id, overview)
        VALUES (?,?,?,?,?,?,?,?,?,?)"""
        cursor = conn.cursor()
        logger.info("Adding missing episodes")
        count = 0
        for values in episode_list:
            try:
                cursor.execute(sql, values)
                count += 1
            except sqlite3.IntegrityError:
                pass
        logger.info(f"Total new episodes added: {count}")

        conn.commit()


def clean_tables():
    with sqlite3.connect(KINOBASE) as conn:
        for table in ("MOVIES", "EPISODES"):
            cursor = conn.execute(f"SELECT path from {table}")
            logger.info(f"Cleaning paths for {table} table")
            [
                conn.execute(f"UPDATE {table} SET path='' WHERE path=?", (i))
                for i in cursor
            ]
        logger.info("Ok")
        conn.commit()


def remove_empty():
    with sqlite3.connect(KINOBASE) as conn:
        for table in ("MOVIES", "EPISODES"):
            logger.info(f"Removing empty rows from {table} table")
            conn.execute(f"DELETE FROM {table} WHERE path IS NULL OR trim(path) = '';")
        logger.info("Ok")
        conn.commit()


def update_request_to_used(request_id):
    """
    :param request_id: request_id from DB or Facebook comment
    """
    with sqlite3.connect(REQUESTS_DB) as conn:
        logger.info("Updating request as used")
        conn.execute(
            "update requests set used=1 where id=?",
            (request_id,),
        )
        conn.commit()


def get_list_of_episode_dicts():
    """
    Convert "EPISODES" table from DB to a list of dictionaries.
    """
    with sqlite3.connect(KINOBASE) as conn:
        try:
            cursor = conn.execute("SELECT * from EPISODES").fetchall()
        except sqlite3.OperationalError:
            logger.info("EPISODES table not available")
            return
        dict_list = []
        for i in cursor:
            relative_srt = os.path.relpath(i[6], EPISODE_COLLECTION)
            dict_list.append(
                {
                    "title": i[0],
                    "season": i[1],
                    "episode": i[2],
                    "writer": i[3],
                    "category": i[4],
                    "path": i[5],
                    "subtitle": i[6],
                    "subtitle_relative": relative_srt,
                    "source": i[7],
                    "id": i[8],
                    "requests": i[10],
                    "last_request": i[11],
                }
            )
        return dict_list


def get_list_of_movie_dicts():
    """
    Convert "MOVIES" table from DB to a list of dictionaries.
    """
    with sqlite3.connect(KINOBASE) as conn:
        try:
            cursor = conn.execute("SELECT * from MOVIES").fetchall()
        except sqlite3.OperationalError:
            logger.info("MOVIES table not available")
            return
        dict_list = []
        for i in cursor:
            if i[5] == "Blacklist" or not i[8]:
                continue
            srt = str(Path(i[8]).with_suffix("")) + ".en.srt"
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
    " Update Kinobot's database. "
    kino_log(KINOLOG)
    create_db_tables()
    radarr_list = get_radarr_list()
    episode_list = get_episodes()
    clean_tables()
    logger.info("Updating Kinobot's database: MOVIES")
    check_missing_movies(radarr_list)
    force_update(radarr_list)
    update_paths(radarr_list)
    logger.info("Updating Kinobot's database: EPISODES")
    update_episode_table(episode_list)
    remove_empty()
