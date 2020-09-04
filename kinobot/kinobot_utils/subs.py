import srt
import json
import kinobot_utils.get_the_kino as get_the_kino

from fuzzywuzzy import fuzz


def search_movie(file, search):
    with open(file, "r") as j:
        films = json.load(j)
        initial = 0
        List = []
        for f in films:
            title = fuzz.ratio(search, f["title"] + " " + str(f["year"]))
            ogtitle = fuzz.ratio(search, f["original_title"] + " " + str(f["year"]))
            if title > ogtitle:
                fuzzy = title
            else:
                fuzzy = ogtitle

            if fuzzy > initial:
                initial = fuzzy
                List.append(f)
        print(initial)
        if initial > 60:
            return List[-1]
        else:
            return


def search_episode(file, search):
    search = search.lower()
    with open(file, "r") as j:
        episodes = json.load(j)
        initial = 0
        List = []
        for f in episodes:
            title = fuzz.ratio(
                search, "{} {}{}".format(f["title"], f["season"], f["episode"]).lower()
            )
            fuzzy = title
            if fuzzy > initial:
                initial = fuzzy
                List.append(f)
        print(initial)
        print(List[-1]['path'])
        if initial > 90:
            return List[-1]
        else:
            return


def get_subtitle(item):
    try:
        with open(item["subtitle"], "r") as it:
            subtitle_generator = srt.parse(it)
            return list(subtitle_generator)
    except FileNotFoundError:
        return


def find_quote(subtitle_list, words):
    initial = 0
    Words = []
    for sub in subtitle_list:
        fuzzy = fuzz.partial_ratio(words, sub.content)
        if fuzzy > initial:
            initial = fuzzy
            Words.append(
                {
                    "message": sub.content,
                    "start": sub.start.seconds,
                    "end": sub.end.seconds,
                    "score": fuzzy,
                }
            )
    return Words[-1]


class Subs:
    def __init__(self, busqueda, words, MOVIE_JSON, TV_JSON, is_episode=False):
        """ search the movie or the episode"""
        if is_episode:
            self.movie = search_episode(TV_JSON, busqueda)
        else:
            self.movie = search_movie(MOVIE_JSON, busqueda)
        """ check if second or quote """
        try:
            t = words
            try:
                m, s = t.split(":")
                sec = int(m) * 60 + int(s)
            except ValueError:
                h, m, s = t.split(":")
                sec = (int(h) * 3600) + (int(m) * 60) + int(s)

            self.pill = get_the_kino.main(
                self.movie["path"], sec, subtitle=None, gif=False
            )
            self.discriminator = "Minute: {}".format(words)
        except ValueError:
            subtitles = get_subtitle(self.movie)
            if subtitles:
                quote = find_quote(subtitles, words)
                self.pill = get_the_kino.main(
                    self.movie["path"], second=None, subtitle=quote, gif=False
                )
                self.discriminator = '"{}"'.format(quote["message"])
            else:
                self.pill = None
