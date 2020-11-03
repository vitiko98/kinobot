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

from fuzzywuzzy import fuzz, process

logger = logging.getLogger(__name__)
REQUESTS_JSON = os.environ.get("REQUESTS_JSON")


def handle_json(discriminator):
    with open(REQUESTS_JSON, "r") as f:
        json_list = json.load(f)
        for j in json_list:
            if discriminator == j:
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
            fuzzy = title if title > ogtitle else ogtitle
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
    logger.info("Looking for the quote: {}".format(words))
    contents = [sub.content for sub in subtitle_list]
    # Extracting 5 for debugging reasons
    final_strings = process.extract(words, contents, limit=5)
    logger.info(final_strings)
    for sub in subtitle_list:
        if final_strings[0][0] == sub.content:
            final_match = {
                "message": sub.content,
                "index": sub.index,
                "start": sub.start.seconds,
                "start_m": sub.start.microseconds,
                "end": sub.end.seconds,
                "score": final_strings[0][1],
            }
    logger.info(final_match)
    return final_match


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
            or cleansub(subtitulos[index].content)[0] == "["
        ):
            lista.append(
                {
                    "message": subtitulos[index].content,
                    "start": subtitulos[index].start.seconds,
                    "start_m": subtitulos[index].start.microseconds,
                    "end": subtitulos[index].end.seconds,
                }
            )
            break
        else:
            lista.append(
                {
                    "message": subtitulos[index].content,
                    "start": subtitulos[index].start.seconds,
                    "start_m": subtitulos[index].start.microseconds,
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
            ) > 4:
                break
            if cleansub(subtitulos[index + 1].content)[0] == ".":
                index += 1
                lista.append(
                    {
                        "message": subtitulos[index].content,
                        "start": subtitulos[index].start.seconds,
                        "start_m": subtitulos[index].start.microseconds,
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
                        "start_m": subtitulos[index].start.microseconds,
                        "end": subtitulos[index].end.seconds,
                    }
                )
            except IndexError:
                break
    if len(lista) > 3:
        return [final]
    else:
        return lista


def replace_request(new_words="Hello", second=None, quote=None):
    if len(new_words) > 80 or len(new_words) < 4:
        raise TypeError

    text = textwrap.fill(new_words, 40)

    def uppercase(matchobj):
        return matchobj.group(0).upper()

    def capitalize(s):
        return re.sub("^([a-z])|[\.|\?|\!]\s*([a-z])|\s+([a-z])(?=\.)", uppercase, s)

    pretty_quote = capitalize(text)
    logger.info("Cleaned new quote: {}".format(pretty_quote))

    if second:
        return {
            "message": pretty_quote,
            "start": second,
            "start_m": 0,
            "end": second + 1,
        }
    else:
        return {
            "message": pretty_quote,
            "start": quote["start"],
            "start_m": 0,
            "end": quote["end"],
        }


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
        self.discriminator = None
        self.movie = search_episode(TV_JSON if is_episode else MOVIE_JSON, busqueda)
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
            logging.info("Time request")
            self.discriminator = "{}{}".format(busqueda, words)
            self.isminute = True if not replace else False
        except ValueError:
            logger.info("Quote request")
            subtitles = get_subtitle(self.movie)
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
                    to_dupe = new_quote["message"]
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
                    to_dupe = quote["message"]
                self.discriminator = '"{}"'.format(to_dupe)
            self.isminute = False
        finally:
            if self.discriminator:
                logger.info("Saving request info")
                handle_json(self.discriminator)
