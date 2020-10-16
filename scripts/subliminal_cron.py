# Python script that handles external subtitles with Subliminal's API

from datetime import timedelta
from operator import itemgetter
import sqlite3
import os
import sys
import logging
from babelfish import Language
from subliminal import (
    region,
    save_subtitles,
    scan_videos,
    refine,
    Movie,
    list_subtitles,
    compute_score,
    download_subtitles,
)

try:
    location = sys.argv[1]
    languages = sys.argv[2]
except IndexError:
    sys.exit(
        "Usage: python3 main.py FOLDER_PATH LANGUAGE\n(One or more languages (comma separated)"
    )


providers_list = ["sucha", "podnapisi", "opensubtitles", "argenteam"]
providers_auth = {
    "opensubtitles": {"username": "whenerespat", "password": os.environ.get("OPEN_PWD")}
}
CACHE_FILE = os.environ.get("HOME") + "/.dogpile.cache.db"
SCORE_DB = os.environ.get("HOME") + "/.score_subliminal.db"

log = False
if log:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(logging.BASIC_FORMAT))
    logging.getLogger("subliminal").addHandler(handler)
    logging.getLogger("subliminal").setLevel(logging.DEBUG)


def create_table(conn):
    try:
        conn.execute(
            """CREATE TABLE scores
            (title TEXT NOT NULL,
            file TEXT NOT NULL,
            score INT NOT NULL)"""
        )
        conn.execute("CREATE UNIQUE INDEX title_og ON scores (title, file);")
        print("Table created successfully")
    except sqlite3.OperationalError:
        pass


def insert_into_table(conn, values):
    sql = """INSERT INTO scores
    (title, file, score)
    VALUES (?,?,?)"""
    cur = conn.cursor()
    try:
        cur.execute(sql, values)
        print("Added to the database")
    except sqlite3.IntegrityError:
        new = "UPDATE scores SET score=? WHERE file=?"
        cur.execute(new, (values[2], values[1]))
        print("Updated")
    finally:
        conn.commit()


def value_exists(conn, path):
    c = conn.cursor()
    c.execute("SELECT 1 FROM scores WHERE file=? LIMIT 1", (path,))
    return c.fetchone() is not None


def get_score_from_db(conn, path):
    c = conn.cursor()
    c.execute("SELECT * FROM scores WHERE file=? LIMIT 1", (path,))
    return c.fetchone()[2]


def download_best_subs(language, i, refiner, conn):
    print_text = i.title if isinstance(i, Movie) else i.name.split("/")[-1]
    print(
        "Searching subtitles for {} [{}]".format(
            print_text,
            language.upper(),
        )
    )

    subtitle_file = (
        os.path.splitext(i.name)[0] + "." + str(Language.fromietf(language)) + ".srt"
    )

    if os.path.isfile(subtitle_file):
        if value_exists(conn, subtitle_file):
            old_score = get_score_from_db(conn, subtitle_file)
            print("File exists in the system with score: {}".format(old_score))
            return
        else:
            print(
                "File exists, but is not available in the database. Downloading again..."
            )
    else:
        print("File doesn't exist")

    refine(
        i,
        movie_refiners=("omdb", "metadata"),
        episode_refiners=("tvdb", "metadata"),
        refiner_configs=refiner,
        embedded_subtitles=False,
    )

    subtitle = list_subtitles(
        [i],
        {Language(Language.fromietf(language).alpha3)},
        providers=providers_list,
        provider_configs=providers_auth,
    )

    score = []
    for s in subtitle[i]:
        matches = s.get_matches(i)
        score.append(
            {"subtitle": s, "score": (compute_score(s, i)), "matches": matches}
        )

    final_subtitles = sorted(score, key=itemgetter("score"), reverse=True)

    if not final_subtitles:
        print("No subtitles found")
        return

    inc = 0
    while True:
        print(
            "[{}] Downloading subtitles with score {} and matches:".format(
                str(final_subtitles[inc]["subtitle"]).split(" ")[0].replace("<", ""),
                final_subtitles[inc]["score"],
            )
        )
        print(final_subtitles[inc]["matches"])
        try:
            download_subtitles([final_subtitles[inc]["subtitle"]])
            save_subtitles(i, [final_subtitles[inc]["subtitle"]])
            insert_into_table(
                conn,
                (
                    i.title if i.title else i.series + i.season + i.episode,
                    subtitle_file,
                    final_subtitles[inc]["score"],
                ),
            )
            break
        except Exception as e:
            print("Something went wrong: {}".format(e))
        inc += 1
        if inc > len(final_subtitles):
            break
    print("#" * 50)


conn = sqlite3.connect(SCORE_DB)
create_table(conn)

region.configure("dogpile.cache.dbm", arguments={"filename": CACHE_FILE})

refiner = {"omdb": {"apikey": os.environ.get("OMDB")}}
videos = scan_videos(sys.argv[1], age=timedelta(weeks=1000))

print("Found {} videos\n{}".format(len(videos), "#" * 50))

for i in videos:
    for language in languages.split(","):
        download_best_subs(language, i, refiner, conn)
