# Almost deprecated module. See "kinodb.py"

import json
import os
from operator import itemgetter
from pathlib import Path

from scan import Scan
from tmdb import TMDB

FILM_COLLECTION = os.environ.get("FILM_COLLECTION")
MOVIE_JSON = os.environ.get("MOVIE_JSON")
TV_COLLECTION = os.environ.get("TV_COLLECTION")
TV_JSON = os.environ.get("TV_JSON")
SUBTITLES = os.environ.get("HOME") + "/subtitles"


def handle_json(file, dictionary=None):
    if not dictionary:
        with open(file, "r") as f:
            return json.load(f)
    else:
        with open(file, "w") as f:
            dictionary = sorted(dictionary, key=itemgetter("title"))
            json.dump(dictionary, f)


def dupe(dictionary, file):
    for i in dictionary:
        if i["path"] == file:
            print("Skipping: {}".format(file))
            return True


def collect_movies(scanner_class, json_file):
    json_movies = handle_json(json_file)

    for i in range(len(scanner_class.movies)):
        movie_file = scanner_class.movies[i]
        if dupe(json_movies, movie_file):
            pass
        else:
            print("Adding {}".format(movie_file))
            name = os.path.basename(movie_file)
            to_srt = Path(name).with_suffix("")
            srt_file = SUBTITLES + "/{}.en.srt".format(to_srt)
            film = TMDB(movie_file)
            try:
                json_movies.append(
                    {
                        "title": film.title,
                        "original_title": film.ogtitle,
                        "year": film.year,
                        "director": film.directors,
                        "country": film.country_list,
                        "popularity": film.popularity,
                        "poster": film.poster,
                        "peak_kino": False,
                        "path": movie_file,
                        "subtitle": srt_file,
                    }
                )
            except AttributeError:
                print("Error: {}".format(movie_file))
                pass
    handle_json(json_file, dictionary=json_movies)


def collect_episodes(scanner_class, json_file):
    json_episodes = handle_json(json_file)
    for i in range(len(scanner_class.tv_shows)):
        episode_file = scanner_class.tv_shows[i]
        if dupe(json_episodes, episode_file):
            pass
        else:
            print("Adding {}".format(episode_file))
            name = os.path.basename(episode_file)
            to_srt = Path(name).with_suffix("")
            srt_file = SUBTITLES + "/shows/{}.en.srt".format(to_srt)
            episode = TMDB(episode_file)
            try:
                json_episodes.append(
                    {
                        "title": episode.title,
                        "season": episode.season,
                        "episode": episode.episode,
                        "path": episode_file,
                        "subtitle": srt_file,
                    }
                )
            except AttributeError:
                print("Error: {}".format(episode_file))
                pass
    handle_json(json_file, dictionary=json_episodes)


def main():
    scanner = Scan(FILM_COLLECTION, TV_COLLECTION)
    collect_movies(scanner, MOVIE_JSON)


main()
