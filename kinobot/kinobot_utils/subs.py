import json
import textwrap
import logging
import os
import re

import srt

try:
    import kinobot_utils.get_the_kino as get_the_kino
    import kinobot_utils.kino_exceptions as kino_exceptions
    import kinobot_utils.random_picks as random_picks
except ImportError:
    pass

from fuzzywuzzy import fuzz

logger = logging.getLogger(__name__)
REQUESTS_JSON = os.environ.get("REQUESTS_JSON")


def handle_json(discriminator):
    with open(REQUESTS_JSON, "r") as f:
        json_list = json.load(f)
        for j in json_list:
            if discriminator == j:
                logger.error("DUPLICATED!")
                raise kino_exceptions.DuplicateRequest
        json_list.append(discriminator)
    with open(REQUESTS_JSON, "w") as f:
        json.dump(json_list, f)


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
        logger.info("Final score for movie: {}".format(initial))
        if initial > 59:
            return List[-1]
        else:
            raise kino_exceptions.NotEnoughSearchScore


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
        logger.info("Final score for episode: {}".format(initial))
        logger.info(List[-1]["path"])
        if initial > 98:
            return List[-1]
        else:
            raise kino_exceptions.NotEnoughSearchScore


def get_subtitle(item):
    with open(item["subtitle"], "r") as it:
        subtitle_generator = srt.parse(it)
        return list(subtitle_generator)


def find_quote(subtitle_list, words):
    initial = 0
    Words = []
    for sub in subtitle_list:
        fuzzy = fuzz.partial_ratio(
            words.replace("\n", " ").lower(), sub.content.replace("\n", " ").lower()
        )
        if fuzzy > initial:
            initial = fuzzy
            Words.append(
                {
                    "message": sub.content,
                    "index": sub.index,
                    "start": sub.start.seconds,
                    "end": sub.end.seconds,
                    "score": fuzzy,
                }
            )
    return Words[-1]


def cleansub(text):
    cleanr = re.compile("<.*?>")
    cleantext = re.sub(cleanr, "", text)
    return cleantext.replace('"', "")


def get_complete_quote(subtitulos, words):
    " Try to detect the context of the line "

    final = find_quote(subtitulos, words)
    if 0 == final["index"]:
        return [final]
    elif len(subtitulos) == final["index"]:
        return [final]

    initial_index = final["index"] - 1
    index = initial_index
    lista = []
    # Backwards
    while True:
        if (
            cleansub(subtitulos[index].content)[0].isupper()
            or cleansub(subtitulos[index].content)[0] == "-"
        ):
            lista.append(
                {
                    "message": subtitulos[index].content,
                    "start": subtitulos[index].start.seconds,
                    "end": subtitulos[index].end.seconds,
                }
            )
            break
        else:
            lista.append(
                {
                    "message": subtitulos[index].content,
                    "start": subtitulos[index].start.seconds,
                    "end": subtitulos[index].end.seconds,
                }
            )
            index = index - 1

    lista.reverse()
    index = initial_index
    # Forward
    while True:
        quote = cleansub(subtitulos[index].content)
        if quote[-1:] == "." or quote[-1:] == "]" or quote[-1:] == "!":
            if (
                subtitulos[index].end.seconds - subtitulos[index + 1].start.seconds
            ) > 5:
                break
            if cleansub(subtitulos[index + 1].content)[0] == ".":
                index += 1
                lista.append(
                    {
                        "message": subtitulos[index].content,
                        "start": subtitulos[index].start.seconds,
                        "end": subtitulos[index].end.seconds,
                    }
                )
            else:
                break
        else:
            try:
                index += 1
                lista.append(
                    {
                        "message": subtitulos[index].content,
                        "start": subtitulos[index].start.seconds,
                        "end": subtitulos[index].end.seconds,
                    }
                )
            except IndexError:
                break
    if len(lista) > 4:
        return [final]
    else:
        return lista


def replace_request(new_words="Hello", second=None, quote=None):
    text = textwrap.fill(new_words, 40)

    def uppercase(matchobj):
        return matchobj.group(0).upper()

    def capitalize(s):
        return re.sub("^([a-z])|[\.|\?|\!]\s*([a-z])|\s+([a-z])(?=\.)", uppercase, s)

    pretty_quote = capitalize(text)
    logger.info("Cleaned new quote: {}".format(pretty_quote))

    if second:
        return {"message": pretty_quote, "start": second, "end": second + 1}
    else:
        return {"message": pretty_quote, "start": quote["start"], "end": quote["end"]}


class Subs:
    def __init__(
        self,
        busqueda,
        words,
        MOVIE_JSON,
        TV_JSON,
        is_episode=False,
        multiple=False,
        replace=None,
    ):
        words = words if not replace else replace[0]
        multiple = multiple if not replace else False
        if is_episode:
            self.movie = search_episode(TV_JSON, busqueda)
        else:
            self.movie = search_movie(MOVIE_JSON, busqueda)
        try:
            t = words
            try:
                m, s = t.split(":")
                sec = int(m) * 60 + int(s)
            except ValueError:
                h, m, s = t.split(":")
                sec = (int(h) * 3600) + (int(m) * 60) + int(s)
            if replace:
                logging.info("Replace request")
                new_quote = replace_request(new_words=replace[1], second=sec)
                self.pill = [
                    get_the_kino.main(
                        self.movie["path"],
                        second=None,
                        subtitle=new_quote,
                        gif=False,
                        multiple=multiple,
                    )
                ]
            else:
                self.pill = [
                    get_the_kino.main(
                        self.movie["path"],
                        second=sec,
                        subtitle=None,
                        gif=False,
                        multiple=multiple,
                    )
                ]
            self.discriminator = words
            logging.info("Time request")
            self.isminute = True if not replace else False
        except ValueError:
            subtitles = get_subtitle(self.movie)
            logger.info("Quote request")
            if not multiple and not replace:
                logger.info("Trying multiple subs")
                quotes = get_complete_quote(subtitles, words)
                multiple_quote = True if len(quotes) > 1 else False
                pils = []
                for q in quotes:
                    logger.info(q["message"])
                    pils.append(
                        get_the_kino.main(
                            self.movie["path"],
                            second=None,
                            subtitle=q,
                            gif=False,
                            multiple=multiple_quote,
                        )
                    )
                self.pill = [random_picks.get_collage(pils, False)]
                self.discriminator = '"{}"'.format(quotes[0]["message"])
            else:
                logger.info("Trying multiple subs")
                quote = find_quote(subtitles, words)
                if replace:
                    logger.info("Replace request")
                    new_quote = replace_request(
                        new_words=replace[1], second=None, quote=quote
                    )
                    self.pill = [
                        get_the_kino.main(
                            self.movie["path"],
                            second=None,
                            subtitle=new_quote,
                            gif=False,
                            multiple=False,
                        )
                    ]
                else:
                    self.pill = [
                        get_the_kino.main(
                            self.movie["path"],
                            second=None,
                            subtitle=quote,
                            gif=False,
                            multiple=multiple,
                        )
                    ]
                self.discriminator = '"{}"'.format(quote["message"])
            self.isminute = False
            handle_json(self.discriminator)
