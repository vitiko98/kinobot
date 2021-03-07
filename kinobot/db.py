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
from operator import itemgetter
from pathlib import Path

import click
import requests
import tmdbsimple as tmdb

import kinobot.exceptions as exceptions
from kinobot.frame import get_dar
from kinobot.utils import (
    kino_log,
    get_video_length,
    get_poster_collage,
)
from kinobot import (
    KINOBASE,
    DISCORD_DB,
    MUSIC_DB,
    FRAMES_DIR,
    RADARR,
    RADARR_URL,
    SONARR_URL,
    SONARR,
    REQUESTS_DB,
    TWITTER_DB,
    TMDB,
    KINOLOG,
)

IMAGE_BASE = "https://image.tmdb.org/t/p/original"
POSTERS_DIR = os.path.join(FRAMES_DIR, "posters")
tmdb.API_KEY = TMDB


logger = logging.getLogger(__name__)


def create_db_tables():
    with sqlite3.connect(KINOBASE) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS MOVIES (title TEXT NOT NULL, og_title TEXT,
            year INT, director TEXT, country TEXT, category TEXT, poster
            TEXT, backdrop TEXT, path TEXT NOT NULL, subtitle TEXT, tmdb
            TEXT NOT NULL, overview TEXT, popularity TEXT, budget TEXT,
            source TEXT, imdb TEXT, runtime TEXT, requests INT,
            last_request INT DEFAULT (0), dar REAL DEFAULT (0),
            verified_subs BOOLEAN DEFAULT (0));

            CREATE TABLE IF NOT EXISTS EPISODES (title TEXT NOT NULL, season INT,
            episode INT, episode_title TEXT, writer TEXT, category TEXT, path TEXT,
            subtitle TEXT, source TEXT, id INT UNIQUE, overview TEXT,
            requests INT DEFAULT (0), last_request INT DEFAULT (0),
            dar REAL DEFAULT (0), verified_subs BOOLEAN DEFAULT (0),
            runtime TEXT, backdrop TEXT, director TEXT);

            CREATE TABLE IF NOT EXISTS USERS (name TEXT UNIQUE, requests INT
            DEFAULT (0), warnings INT DEFAULT (0), digs INT DEFAULT (0),
            indie INT DEFAULT (0), historician INT DEFAULT (0),
            animation INT DEFAULT (0), blocked BOOLEAN DEFAULT (0));

            CREATE TABLE IF NOT EXISTS MUSIC (id UNIQUE NOT NULL,
            artist NOT NULL, title NOT NULL);
            """
        )
        conn.commit()


def create_music_db():
    with sqlite3.connect(MUSIC_DB) as conn:
        conn.executescript(
            """CREATE TABLE IF NOT EXISTS MUSIC (id TEXT UNIQUE NOT NULL, artist TEXT
            NOT NULL, title TEXT NOT NULL, category TEXT);

            CREATE TABLE IF NOT EXISTS requests (
                user    TEXT    NOT NULL,
                comment TEXT    NOT NULL,
                type    TEXT    NOT NULL,
                movie   TEXT    NOT NULL,
                content TEXT    NOT NULL,
                id      TEXT    NOT NULL,
                used    BOOLEAN DEFAULT (0),
                verified BOOLEAN DEFAULT (0),
                priority BOOLEAN DEFAULT (0)
                );"""
        )
        conn.commit()


def create_request_db():
    with sqlite3.connect(REQUESTS_DB) as conn:
        conn.executescript(
            """CREATE TABLE IF NOT EXISTS requests (
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
            );

            CREATE TABLE IF NOT EXISTS history (content TEXT UNIQUE);"""
        )

        conn.commit()


def create_discord_db():
    with sqlite3.connect(DISCORD_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
            user    TEXT    NOT NULL,
            discriminator TEXT  NOT NULL UNIQUE,
            name_history TEXT
            );
            CREATE TABLE IF NOT EXISTS limits
            (id INT UNIQUE, hits INT DEFAULT (1));
            """
        )
        conn.commit()


def create_twitter_db():
    with sqlite3.connect(TWITTER_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
            id INT UNIQUE,
            username TEXT  NOT NULL,
            patreon_tier TEXT,
            discord_id TEXT,
            hits INT DEFAULT (1)
            );
            CREATE TABLE IF NOT EXISTS mentions
            (id INT UNIQUE);
            """
        )
        conn.commit()


def insert_twitter_mention_id(mention_id):
    """
    raises sqlite3.IntegrityError
    """
    with sqlite3.connect(TWITTER_DB) as conn:
        logger.info(f"Inserting mention ID: {mention_id}")
        conn.execute(
            "insert into mentions (id) values (?)",
            (mention_id,),
        )


def get_last_mention_id():
    with sqlite3.connect(TWITTER_DB) as conn:
        last_id = conn.execute(
            "SELECT id FROM mentions ORDER BY id DESC LIMIT 1;"
        ).fetchone()
        if last_id:
            return last_id[0]


def insert_episode_into_table(values):
    """
    :param values: tuple from insert_episode
    """
    with sqlite3.connect(KINOBASE) as conn:
        sql = """INSERT INTO EPISODES
        (title, overview, id, season, episode, episode_title,
        category, path, backdrop, dar)
        VALUES (?,?,?,?,?,?,?,?,?,?)"""
        cur = conn.cursor()
        try:
            cur.execute(sql, values)
            conn.commit()
        except sqlite3.IntegrityError:
            logger.info(f"Duplicate: {values[0]}")


def check_missing_sonarr(sonarr_list):
    """
    :param radarr_list: Radarr dictionary from get_radarr_list
    """
    logger.info("Checking missing episodes")
    with sqlite3.connect(KINOBASE) as conn:
        indexed_ids = [id_[0] for id_ in conn.execute("SELECT id from EPISODES")]
        logger.info(f"Indexed episodes: {len(indexed_ids)}")
        count = 0
        for episode in sonarr_list:
            if any(str(i) == str(episode["id"]) for i in indexed_ids):
                continue

            logger.info(f"Adding {episode['id']}")
            values = list(episode.values())
            values.append(get_dar(episode.get("path")))
            insert_episode_into_table(tuple(values))

            count += 1
        if count == 0:
            logger.info("No missing episodes")


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
            conn.commit()
        except sqlite3.IntegrityError:
            logger.info(f"Duplicate: {values[0]}")


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
        i["movieFile"].get("mediaInfo", {}).get("runTime", i.get("runtime")),
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
                    i["movieFile"]
                    .get("mediaInfo", {})
                    .get("runTime", i.get("runtime")),
                    i.get("tmdbId"),
                ),
            )
        conn.commit()


def update_paths_movies(radarr_list):
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


def update_paths_episodes(sonarr_list):
    with sqlite3.connect(KINOBASE) as conn:
        for i in sonarr_list:
            conn.execute(
                "UPDATE EPISODES SET path=? WHERE id=?",
                (
                    i["path"],
                    i["id"],
                ),
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


def get_requests(filter_type="movies", priority_only=False, verified=True):
    """
    :param filter: movies or episodes
    :param priority_only: filter requests without priority
    :param verified: include verified requests
    """
    with sqlite3.connect(REQUESTS_DB) as conn:
        result = conn.execute("select * from requests where used=0").fetchall()
        requests = []
        for i in result:
            #        is_episode_ = is_episode(i[1])

            #       if filter_type == "movies" and is_episode_:
            #                continue

            #           if filter_type == "episodes" and not is_episode_:
            #              continue

            # filter any music videos
            if i[3].startswith("MUSIC") and any(
                filter_type == filter_ for filter_ in ("movies", "episodes")
            ):
                continue

            # filter any movies and episodes
            if not i[3].startswith("MUSIC") and filter_type == "music":
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
                    "on_demand": False,
                }
            )

        random.shuffle(requests)

        if priority_only:
            return [request for request in requests if request.get("priority")]

        if verified:
            return requests

        return [request for request in requests if not request.get("verified")]


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


def update_twitter_patreon_tier(user, tier):
    """
    :param user: User class from tweepy
    :param tier: patreon or discord role
    """
    with sqlite3.connect(TWITTER_DB) as conn:
        try:
            conn.execute(
                "insert into users (id, username, patreon_tier) values (?,?,?)",
                (user.id, user.screen_name, tier),
            )
            logger.info(f"Registered new Twitter user: {user.screen_name}")
        except sqlite3.IntegrityError:
            pass

        conn.execute(
            "update users set patreon_tier=? where id=?",
            (
                tier,
                user.id,
            ),
        )
        logger.info(f"Updated tier to {tier} from user {user.screen_name}")


def get_twitter_patreon_tier(user_id):
    with sqlite3.connect(TWITTER_DB) as conn:
        tier = conn.execute(
            "select patreon_tier from users where id=?",
            (user_id,),
        ).fetchone()
        if tier:
            return tier[0]


def handle_discord_limits(discord_id, limit=3):
    with sqlite3.connect(DISCORD_DB) as conn:
        try:
            conn.execute(
                "insert into limits (id) values (?)",
                (discord_id,),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass

        hits = conn.execute(
            "select hits from limits where id=? and hits <= ?",
            (
                discord_id,
                limit,
            ),
        ).fetchone()

        logger.info(f"Hits: {hits}")
        if not hits:
            raise exceptions.LimitExceeded

        conn.execute("update limits set hits=hits+1 where id=?", (discord_id,))


def insert_request_to_history(content):
    """
    :param content: request content ID
    :raises exception.DuplicateRequest
    """
    with sqlite3.connect(REQUESTS_DB) as conn:
        try:
            conn.execute(
                "insert into history (content) values (?)",
                (content,),
            )
            conn.commit()
            logger.info(f"Updated history for database: {REQUESTS_DB}")
        except sqlite3.IntegrityError:
            raise exceptions.DuplicateRequest(
                f"Duplicate request found with ID '{content}'"
            )


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


def insert_music_video(video_id, artist, title, category):
    """
    :param video_id: video_id
    :param artist: artist
    :param title: title
    :raises sqlite3.IntegrityError
    """
    with sqlite3.connect(MUSIC_DB) as conn:
        conn.execute(
            "INSERT INTO MUSIC (id, artist, title, category) VALUES (?,?,?,?)",
            (
                video_id,
                artist,
                title,
                category,
            ),
        )
        conn.commit()


def search_db_tracks(query):
    """
    Return a list of (id, artist, title, category) tuples.
    """
    search_query = "%" + query + "%"
    with sqlite3.connect(MUSIC_DB) as conn:
        results = conn.execute(
            "select * from MUSIC where (id || '--' "
            "|| artist || '--' || title || '--' || category) like ?",
            (search_query,),
        ).fetchall()
        random.shuffle(results)
        return results[:10]


def update_music_category(video_id, category):
    with sqlite3.connect(MUSIC_DB) as conn:
        conn.execute(
            "update music set category=? where id=?",
            (
                category,
                video_id,
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


def verify_request(request_id, database=REQUESTS_DB):
    logger.info(f"Verifying request: {request_id}")
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE requests SET verified=1, used=0, priority=1 where id=?",
            (request_id,),
        )
        conn.commit()
    return f"Verified: {request_id}."


def insert_request(request_tuple, database=REQUESTS_DB):
    """
    :param request_tuple (user, comment, command, title, '|' separated content,
    comment id, priority)
    :param database: custom database
    :raises sqlite3.IntegrityError
    """
    with sqlite3.connect(database) as conn:
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
            "Updating last_request timestamp for episode "
            f"{episode_title} ({KINOBASE})",
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
            "select comment, id, user from requests where (user || '--' "
            "|| type || '--' || comment) like ? and used=0",
            (search_query,),
        ).fetchall()

    random.shuffle(requests)
    return requests[:50]


def search_movies(query):
    search_query = "%" + query + "%"
    with sqlite3.connect(KINOBASE) as conn:
        requests = conn.execute(
            "select title, year, tmdb from movies where (title || '--' "
            "|| og_title || '--' || country || '--' || category || '--' || "
            "director) like ?",
            (search_query,),
        ).fetchall()

    random.shuffle(requests)
    return requests[:7]


def db_command_to_dict(database, command):
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn_ = conn.cursor()
        conn_.execute(command)
        return [dict(row) for row in conn_.fetchall()]


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
            "Updating last_request timestamp for movie "
            f"{movie['title']} ({KINOBASE})",
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
            conn.execute("INSERT INTO USERS (name) VALUES (?)", (user,))
            logger.info(f"Adding user: {user}")
        except sqlite3.IntegrityError:
            pass

        logger.info("Updating requests count")
        conn.execute("UPDATE USERS SET requests=requests+1 WHERE name=?", (user,))
        if movie["popularity"] <= 9:
            logger.info(f"Updating digs count")
            conn.execute("UPDATE USERS SET digs=digs+1 WHERE name=?", (user,))
        if movie["budget"] <= 750000:
            logger.info(f"Updating indie count")
            conn.execute("UPDATE USERS SET indie=indie+1 WHERE name=?", (user,))
        if movie["year"] < 1940:
            logger.info(f"Updating historician count")
            conn.execute(
                "UPDATE USERS SET historician=historician+1 WHERE name=?", (user,)
            )
        conn.commit()


def clean_tables():
    with sqlite3.connect(KINOBASE) as conn:
        for table in ("MOVIES", "EPISODES"):
            logger.info("Cleaning paths for %s table", table)
            conn.execute(f"UPDATE {table} SET path=''")
        logger.info("Ok")
        conn.commit()


def remove_empty():
    with sqlite3.connect(KINOBASE) as conn:
        for table in ("MOVIES", "EPISODES"):
            logger.info(f"Removing empty rows from {table} table")
            conn.execute(f"DELETE FROM {table} WHERE path IS NULL OR trim(path) = '';")
        logger.info("Ok")
        conn.commit()


def delete_music_video(video_id):
    with sqlite3.connect(MUSIC_DB) as conn:
        conn.execute(
            "delete from music where id=?",
            (video_id,),
        )
        conn.commit()


def remove_request(request_id, database=REQUESTS_DB):
    with sqlite3.connect(database) as conn:
        conn.execute(
            "update requests set used=1 where id=?",
            (request_id,),
        )
        conn.commit()
    return f"Updated as used: {request_id}."


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


def get_list_of_music_dicts():
    """
    Convert "MUSIC" table from DB to a list of dictionaries.
    """
    with sqlite3.connect(MUSIC_DB) as conn:
        try:
            cursor = conn.execute("SELECT * from MUSIC").fetchall()
        except sqlite3.OperationalError:
            logger.info("EPISODES table not available")
            return
        dict_list = []
        for i in cursor:
            if "Blacklist" == i[3]:
                continue
            dict_list.append(
                {
                    "id": i[0],
                    "artist": i[1],
                    "title": i[2],
                    "category": i[3],
                }
            )
        return dict_list


def get_sonarr_list():
    " Fetch list from Sonarr server. "
    session = requests.Session()
    logger.info("Retrieving list from Sonarr")
    response = session.get(f"{SONARR_URL}/api/series?apiKey={SONARR}")
    response.raise_for_status()
    series = response.json()

    episode_list = []
    for serie in series:
        if not serie.get("sizeOnDisk", 0):
            continue

        try:
            image = [
                image.get("url")
                for image in serie.get("images")
                if image.get("coverType") == "fanart"
            ][0]
            image = SONARR_URL + image
        except IndexError:
            image = None

        serie_r = session.get(
            f"{SONARR_URL}/api/episode",
            params={"apiKey": SONARR, "seriesId": serie.get("id")},
        )
        serie_r.raise_for_status()
        episodes = serie_r.json()

        for episode in episodes:
            if not episode.get("hasFile"):
                continue

            episode_list.append(
                {
                    "title": serie.get("title"),
                    "overview": episode.get("overview"),
                    "id": (
                        f"{serie.get('tvdbId', serie.get('imdbId'))}"
                        f"{episode.get('seasonNumber')}"
                        f"{episode.get('episodeNumber')}"
                    ),
                    "season": episode.get("seasonNumber"),
                    "episode": episode.get("episodeNumber"),
                    "episode_title": episode.get("title", "N/A"),
                    "category": "Unknown",
                    "path": episode.get("episodeFile").get("path"),
                    "backdrop": image,
                }
            )

    return episode_list


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
            dict_list.append(
                {
                    "title": i[0],
                    "season": i[1],
                    "episode": i[2],
                    "episode_title": i[3],
                    "writer": i[4],
                    "category": i[5],
                    "path": i[6],
                    "subtitle": os.path.splitext(i[6])[0] + ".en.srt",
                    "source": i[7],
                    "id": i[9],
                    "requests": i[11],
                    "dar": i[13],
                    "runtime": i[12],
                    "last_request": i[14],
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

            srt = os.path.splitext(i[8])[0] + ".en.srt"

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
    " Update movies table. "
    kino_log(KINOLOG)
    create_db_tables()
    radarr_list = get_radarr_list()
    clean_tables()
    logger.info("Updating Kinobot's database: MOVIES")
    check_missing_movies(radarr_list)
    force_update(radarr_list)
    update_paths_movies(radarr_list)
    logger.info("Updating Kinobot's database: EPISODES")
    sonarr_list = get_sonarr_list()
    check_missing_sonarr(sonarr_list)
    update_paths_episodes(sonarr_list)


@click.command("posters")
@click.option("--count", "-c", default=20, help="number of collages")
def generate_static_poster_collages(count):
    " Generate static poster collages from database. "
    movies = get_list_of_movie_dicts()

    os.makedirs(POSTERS_DIR, exist_ok=True)

    for _ in range(count):
        collage = get_poster_collage(movies)
        collage.save(os.path.join(POSTERS_DIR, f"{random.randint(0, 1000)}.jpg"))
