# The purpose of this database is to edit categories more easily. The database
# is not implemented (TODO!) to the main module which still uses json (that's
# why we generate a new list of dicts)

import os
import sqlite3
import json
from pathlib import Path

from scan import Scan
from tmdb import TMDB

SUBTITLES = os.environ.get("HOME") + "/subtitles"
FILM_COLLECTION = os.environ.get("FILM_COLLECTION")
MOVIE_JSON = os.environ.get("MOVIE_JSON")
TV_COLLECTION = os.environ.get("TV_COLLECTION")


def create_table(conn):
    try:
        conn.execute(
            """CREATE TABLE MOVIES
            (title TEXT NOT NULL,
            og_title TEXT NOT NULL,
            year INT NOT NULL,
            director TEXT NOT NULL,
            country TEXT NOT NULL,
            category TEXT NOT NULL,
            poster TEXT NOT NULL,
            backdrop TEXT NOT NULL,
            path TEXT NOT NULL,
            subtitle TEXT NOT NULL);"""
        )
        conn.execute("CREATE UNIQUE INDEX title_og ON MOVIES (title,og_title);")
        print("Table created successfully")
    except sqlite3.OperationalError as e:
        print(e)


def insert_into_table(conn, values):
    sql = """INSERT INTO MOVIES
    (title, og_title, year, director, country, category,
    poster, backdrop, path, subtitle)
    VALUES (?,?,?,?,?,?,?,?,?,?)"""
    cur = conn.cursor()
    try:
        cur.execute(sql, values)
    except sqlite3.IntegrityError as e:
        print(
            "{} ({}) has been detected as a duplicate title. Do something about it!".format(
                values[0], values[8]
            )
        )
    finally:
        conn.commit()


def is_not_missing(real_path, path_list):
    for i in path_list:
        if i == real_path:
            return True


def generate_json(conn, TABLE):
    print("Generating json...")
    cursor = conn.execute("SELECT * from {}".format(TABLE))
    new_json = []
    for i in cursor:
        new_json.append(
            {
                "title": i[0],
                "original_title": i[1],
                "year": i[2],
                "director": i[3],
                "country": i[4],
                "category": i[5],
                "poster": i[6],
                "path": i[8],
                "subtitle": i[9],
            }
        )
    with open(MOVIE_JSON, "w", encoding="utf-8") as f:
        json.dump(new_json, f, ensure_ascii=False, indent=4)
        print("Ok")


def missing_files(conn, TABLE, scanner_movie_or_episode):
    cursor = conn.execute("SELECT path from {}".format(TABLE))
    for i in cursor:
        if is_not_missing(i[0], scanner_movie_or_episode):
            continue
        else:
            print("Deleting missing data with file: {}".format(i[0]))
            cursor.execute("DELETE FROM {} WHERE path=?".format(TABLE), (i))
            conn.commit()


def value_exists(conn, path):
    c = conn.cursor()
    c.execute("SELECT 1 FROM MOVIES WHERE path=? LIMIT 1", (path,))
    return c.fetchone() is not None


def collect_movies(conn, scanner_class):
    print("Total files: {}".format(len(scanner_class.movies)))

    for i in range(len(scanner_class.movies)):
        movie_file = scanner_class.movies[i]
        # Just in case, to avoid wasting API calls
        if value_exists(conn, movie_file):
            continue
        # print("Adding {}".format(movie_file))
        name = os.path.basename(movie_file)
        to_srt = Path(name).with_suffix("")
        srt_file = SUBTITLES + "/{}.en.srt".format(to_srt)
        try:
            film = TMDB(movie_file)
        except IndexError:
            print("{} returned no results. Fix it!!!".format(movie_file))
            continue
        try:
            values = (
                film.title,
                film.ogtitle,
                film.year,
                film.directors,
                film.country_list,
                "Certified Kino",
                film.poster,
                film.backdrop,
                movie_file,
                srt_file,
            )
            insert_into_table(conn, values)
            print("Added: {}".format(film.title))
        except AttributeError as e:
            print("Error: {}. Check {}!!!".format(e, movie_file))


def main():
    scanner = Scan(FILM_COLLECTION, TV_COLLECTION)
    conn = sqlite3.connect(os.environ.get("KINOBASE"))
    print("Ok")
    create_table(conn)
    missing_files(conn, "MOVIES", scanner.movies)
    collect_movies(conn, scanner)
    generate_json(conn, "MOVIES")
    conn.close()


main()
