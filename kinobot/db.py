#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import os
import random
import sqlite3
import time
from datetime import timedelta
from operator import itemgetter
from pathlib import Path

from plexapi.server import PlexServer
import click
import requests
import tmdbsimple as tmdb

import kinobot.exceptions as exceptions
from kinobot.frame import get_dar
from kinobot.utils import (
    kino_log,
    is_episode,
    check_list_of_watched_plex,
    get_video_length,
    get_poster_collage,
)
from kinobot import (
    KINOBASE,
    EPISODE_COLLECTION,
    DISCORD_DB,
    FRAMES_DIR,
    RADARR,
    RADARR_URL,
    REQUESTS_DB,
    TMDB,
    KINOLOG,
    PLEX_URL,
    PLEX_TOKEN,
)

IMAGE_BASE = "https://image.tmdb.org/t/p/original"
POSTERS_DIR = os.path.join(FRAMES_DIR, "posters")
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
                last_request INT DEFAULT (0), dar REAL DEFAULT (0),
                verified_subs BOOLEAN DEFAULT (0));
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
                requests INT DEFAULT (0), last_request INT DEFAULT (0),
                dar REAL DEFAULT (0), verified_subs BOOLEAN DEFAULT (0),
                runtime TEXT);
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
                animation INT DEFAULT (0), blocked BOOLEAN DEFAULT (0);"""
            )
            logger.info("Table created: USERS")
        except sqlite3.OperationalError:
            pass

        conn.commit()


def create_request_db():
    with sqlite3.connect(REQUESTS_DB) as conn:
        try:
            conn.execute(
                """CREATE TABLE requests (
                    user    TEXT    NOT NULL,
                    comment TEXT    NOT NULL
                                    UNIQUE,
                    type    TEXT    NOT NULL,
                    movie   TEXT    NOT NULL,
                    content TEXT    NOT NULL,
                    id      TEXT    NOT NULL,
                    used    BOOLEAN DEFAULT (0),
                    verified BOOLEAN DEFAULT (0),
                    priority BOOLEAN DEFAULT (0),
                    discriminator TEXT
                    );"""
            )
            logging.info("Created new table: requests")
            conn.commit()
        except sqlite3.OperationalError:
            pass


def create_discord_db():
    with sqlite3.connect(DISCORD_DB) as conn:
        try:
            conn.execute(
                """CREATE TABLE users (
                    user    TEXT    NOT NULL,
                    discriminator TEXT  NOT NULL UNIQUE,
                    name_history TEXT
                    );"""
            )
            logging.info("Created new table: users")
            conn.commit()
        except sqlite3.OperationalError:
            pass


def insert_into_table(values):
    """
    :param values: tuple from insert_movie
    """
    with sqlite3.connect(KINOBASE) as conn:
        sql = """INSERT INTO MOVIES
        (title, og_title, year, director, country, category,
        poster, backdrop, path, subtitle, tmdb, overview,
        popularity, budget, source, imdb, runtime, dar, requests)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)"""
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
    display_aspect_ratio = get_dar(filename)

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
        input(f"Category for '{movie.title}':\n- ") or "Certified Kino",
        f"{IMAGE_BASE}{getattr(movie, 'poster_path', 'Unknown')}",
        f"{IMAGE_BASE}{getattr(movie, 'backdrop_path', 'Unknown')}",
        filename,
        srt,
        i["tmdbId"],
        i["overview"],
        movie.popularity,
        movie.budget,
        i["movieFile"]["quality"]["quality"]["name"].split("-")[0],
        i["imdbId"],
        i["movieFile"]["mediaInfo"]["runTime"],
        display_aspect_ratio,
    )

    insert_into_table(values)

    logger.info(f"Added: {movie.title}")


def update_dar_from_table(table="movies"):
    """
    Update all files with missing DAR from table.

    :param table
    """
    with sqlite3.connect(KINOBASE) as conn:
        paths = conn.execute(f"select path from {table} where dar=0").fetchall()
        logger.info(f"Files with missing DAR: {len(paths)}")
        for path in paths:
            dar = get_dar(path[0])
            conn.execute(
                f"update {table} set dar=? where path=?",
                (
                    dar,
                    path[0],
                ),
            )
            conn.commit()


def update_runtime_from_table(table="movies"):
    """
    Update all files with missing runtime from table.

    :param table
    """
    with sqlite3.connect(KINOBASE) as conn:
        paths = conn.execute(f"select path from {table} where runtime=0").fetchall()
        logger.info(f"Files with missing DAR: {len(paths)}")
        for path in paths:
            runtime = get_video_length(path)
            conn.execute(
                f"update {table} set runtime=? where path=?",
                (
                    runtime,
                    path[0],
                ),
            )
            conn.commit()


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


def get_requests(filter_type="movies", priority_only=False):
    """
    :param filter: movies or episodes
    :param priority_only: filter requests without priority
    """
    with sqlite3.connect(REQUESTS_DB) as conn:
        result = conn.execute("select * from requests where used=0").fetchall()
        requests = []
        for i in result:
            is_episode_ = is_episode(i[1])

            if filter_type == "movies" and is_episode_:
                continue

            if filter_type == "episodes" and not is_episode_:
                continue

            requests.append(
                {
                    "user": i[0],
                    "comment": i[1],
                    "type": i[2],
                    "movie": i[3],
                    "content": i[4].split("|"),
                    "id": i[5],
                    "verified": i[7],
                    "priority": i[8],
                }
            )

        random.shuffle(requests)

        if priority_only:
            return [request for request in requests if request.get("priority")]

        return requests


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


def update_name_from_requests(old_name, new_name):
    with sqlite3.connect(REQUESTS_DB) as conn:
        conn.execute(
            "update requests set user=? where user=?",
            (
                new_name,
                old_name,
            ),
        )
        conn.commit()


def register_discord_user(name, discriminator):
    """
    :param name: discord name
    :param discriminator: discord discriminator
    :raises sqlite3.IntegrityError
    """
    with sqlite3.connect(DISCORD_DB) as conn:
        conn.execute(
            "insert into users (user, discriminator) values (?,?)",
            (
                name,
                discriminator,
            ),
        )
        conn.commit()


def execute_sql_command(command, database=None):
    """
    :param command: sqlite3 command
    :param database: custom database
    :raises sqlite3.Error
    """
    database = KINOBASE if not database else database
    with sqlite3.connect(database) as conn:
        conn.execute(command)
        conn.commit()


def get_name_from_discriminator(name_discriminator):
    """
    :param ctx_obj: name and discriminator from discord
    """
    with sqlite3.connect(DISCORD_DB) as conn:
        return conn.execute(
            "select user from users where discriminator=? limit 1",
            (name_discriminator,),
        ).fetchone()


def verify_request(request_id):
    logger.info(f"Verifying request: {request_id}")
    with sqlite3.connect(REQUESTS_DB) as conn:
        conn.execute(
            "UPDATE requests SET verified=1, used=0, priority=1 where id=?",
            (request_id,),
        )
        conn.commit()
    return f"Verified: {request_id}."


def insert_request(request_tuple):
    """
    :request_tuple (user, comment, command, title, '|' separated content,
    comment id, priority)
    :raises sqlite3.IntegrityError
    """
    with sqlite3.connect(REQUESTS_DB) as conn:
        conn.execute(
            """insert into requests
                    (user, comment, type, movie, content, id, priority)
                    values (?,?,?,?,?,?,?)""",
            (request_tuple),
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


def get_user_queue(user):
    queue = db_command_to_dict(
        REQUESTS_DB, f"select comment, id from requests where user='{user}' and used=0"
    )
    return [f"{i['comment']} - {i['id']}" for i in queue]


def get_priority_queue():
    queue = db_command_to_dict(
        REQUESTS_DB, f"select comment, id from requests where priority=1 and used=0"
    )
    return [f"{i['comment']} - {i['id']}" for i in queue]


def get_discord_user_list():
    with sqlite3.connect(DISCORD_DB) as conn:
        users = conn.execute("select user from users").fetchall()
        return [user[0] for user in users]


def purge_user_requests(user):
    with sqlite3.connect(REQUESTS_DB) as conn:
        conn.execute(
            "update requests set used=1 where user=?",
            (user,),
        )
        conn.commit()


def search_requests(query):
    search_query = "%" + query + "%"
    with sqlite3.connect(REQUESTS_DB) as conn:
        requests = conn.execute(
            "select comment, id from requests where (user || '--' "
            "|| type || '--' || comment) like ? and used=0",
            (search_query,),
        ).fetchall()
    if requests:
        return [f"**{req[0]}** - `{req[1]}`" for req in requests]


def db_command_to_dict(database, command):
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn_ = conn.cursor()
        conn_.execute(command)
        return [dict(row) for row in conn_.fetchall()]


def verify_movie_subtitles():
    movies = check_list_of_watched_plex()
    with sqlite3.connect(KINOBASE) as conn:
        for movie in movies:
            conn.execute(
                "update movies set verified_subs=1 where title=?",
                (movie,),
            )
        conn.commit()
    return len(movies)


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
        srt_file = os.path.splitext(path)[0] + ".en.srt"
        runtime = str(timedelta(milliseconds=episode.duration))
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
                "N/A",
                int(
                    episode.guid.split("://")[-1]
                    .replace("?lang=en", "")
                    .replace("/", "")
                ),
                episode.summary,
                runtime.split(".")[0],
            )
        )

    return episode_tuples


def update_episode_table(episode_list):
    with sqlite3.connect(KINOBASE) as conn:
        logger.info("Updating episode paths")
        for episode in episode_list:
            conn.execute(
                "UPDATE EPISODES SET path=?, subtitle=?, runtime=? WHERE id=?",
                (
                    episode[5],
                    episode[6],
                    episode[10],
                    episode[8],
                ),
            )

        sql = """INSERT INTO EPISODES
        (title, writer, season, episode, category,
        path, subtitle, source, id, overview, runtime)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)"""
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


def remove_request(request_id):
    with sqlite3.connect(REQUESTS_DB) as conn:
        conn.execute(
            "delete from requests where id=?",
            (request_id,),
        )
        conn.commit()
    return f"Deleted: {request_id}."


def update_discord_name(user, discriminator):
    with sqlite3.connect(DISCORD_DB) as conn:
        conn.execute(
            "update users set user=? where discriminator=?",
            (
                user,
                discriminator,
            ),
        )
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
                    "dar": i[12],
                    "runtime": i[14],
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
                    "dar": i[20],
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
    update_dar_from_table("episodes")


@click.command("posters")
@click.option("--count", "-c", default=20, help="number of collages")
def generate_static_poster_collages(count):
    " Generate static poster collages from database. "
    movies = get_list_of_movie_dicts()

    os.makedirs(POSTERS_DIR, exist_ok=True)

    for _ in range(count):
        collage = get_poster_collage(movies)
        collage.save(os.path.join(POSTERS_DIR, f"{random.randint(0, 1000)}.jpg"))
