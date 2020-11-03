# The purpose of this database is to edit categories more easily. The database
# is not implemented (TODO!) to the main module which still uses json (that's
# why we generate a new list of dicts)

import json
import os
import sqlite3
import sys
from operator import itemgetter
from pathlib import Path

import requests
import tmdbsimple as tmdb

SUBTITLES = os.environ.get("HOME") + "/subtitles"
RADARR = os.environ.get("RADARR")
FILM_COLLECTION = os.environ.get("FILM_COLLECTION")
MOVIE_JSON = os.environ.get("MOVIE_JSON")
TV_COLLECTION = os.environ.get("TV_COLLECTION")
TMDB_KEY = os.environ.get("TMDB")
tmdb.API_KEY = TMDB_KEY


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
    except sqlite3.IntegrityError:
        print(
            "{} ({}) has been detected as a duplicate title. Do something about it!".format(
                values[0], values[8]
            )
        )
    finally:
        conn.commit()


def generate_json(conn):
    print("Generating json...")
    cursor = conn.execute("SELECT * from MOVIES")
    new_json = []
    count = 0
    for i in cursor:
        if i[5] == "Blacklist":
            continue
        if not i[8]:
            count += 1
            continue
        to_srt = Path(i[8]).with_suffix("")
        srt = "{}.{}".format(to_srt, "en.srt")
        new_json.append(
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
            }
        )
    print("Movies with missing paths: {}".format(count))
    with open(MOVIE_JSON, "w", encoding="utf-8") as f:
        sorted_list = sorted(new_json, key=itemgetter("title"))
        json.dump(sorted_list, f, ensure_ascii=False, indent=4)
        print("Ok")


def is_not_missing(radarr_title, database_titles):
    for i in database_titles:
        if i == radarr_title:
            return True
    print("{} is missing".format(radarr_title))


def insert_movie(conn, i):  # i = radarr_item
    filename = i["movieFile"]["path"]
    to_srt = Path(filename).with_suffix("")
    srt = "{}.{}".format(to_srt, "en.srt")
    movie = tmdb.Movies(i["tmdbId"])
    movie.info()
    country_list = ", ".join([i["name"] for i in movie.production_countries])
    IMAGE_BASE = "https://image.tmdb.org/t/p/original"
    movie.credits()
    dirs = [m["name"] for m in movie.crew if m["job"] == "Director"]
    values = (
        movie.title,
        str(movie.original_title) if movie.original_title else movie.title,
        movie.release_date.split("-")[0],
        ", ".join(dirs),
        country_list,
        "Certified Kino",
        IMAGE_BASE + str(movie.poster_path) if movie.poster_path else "Unknown",
        IMAGE_BASE + str(movie.backdrop_path) if movie.backdrop_path else "Unknown",
        filename,
        srt,
    )
    insert_into_table(conn, values)
    print("Added: {}".format(movie.title))


def get_json():
    url = "http://radarr.caretas.club/api/v3/movie?apiKey=" + RADARR
    r = requests.get(url)
    r.raise_for_status()
    return json.loads(r.content)


def clean_paths(conn):
    cursor = conn.execute("SELECT path from MOVIES")
    print("Cleaning paths...")
    for i in cursor:
        conn.execute("UPDATE MOVIES SET path='' WHERE path=?", (i))
    conn.commit()
    print("Ok")


def update_paths(conn, radarr_list):
    print("Updating paths")
    for i in radarr_list:
        conn.execute(
            "UPDATE MOVIES SET path=? WHERE title=?",
            ((i["movieFile"]["path"]), i["title"]),
        )
    conn.commit()
    print("Ok")


def check_missing_movies(conn, radarr_list):
    print("Checking missing movies...")
    indexed_titles_db = [title[0] for title in conn.execute("SELECT title from MOVIES")]
    count = 0
    for movie in radarr_list:
        if not is_not_missing(movie["title"], indexed_titles_db):
            print("Adding {}...".format(movie["title"]))
            count += 1
            insert_movie(conn, movie)
    if count == 0:
        print("No missing movies")


def main():
    # Fetch list from Radarr server
    radarr_json = get_json()
    radarr_list = [i for i in radarr_json if i["hasFile"]]
    # Update the table and generate the json
    conn = sqlite3.connect(os.environ.get("KINOBASE"))
    create_table(conn)
    check_missing_movies(conn, radarr_list)
    clean_paths(conn)
    update_paths(conn, radarr_list)
    generate_json(conn)
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
