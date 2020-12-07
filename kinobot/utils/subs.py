import json
import numpy as np
import time
import logging
import os
import re
import textwrap

import srt

try:
    import utils.get_the_kino as get_the_kino
    import utils.kino_exceptions as kino_exceptions
    import utils.random_picks as random_picks
except ImportError:
    pass

from fuzzywuzzy import fuzz, process

logger = logging.getLogger(__name__)
REQUESTS_JSON = os.environ.get("REQUESTS_JSON")


def handle_json(discriminator):
    with open(REQUESTS_JSON, "r") as f:
        json_list = json.load(f)
        if any(j.replace('"', "") in discriminator for j in json_list):
            raise kino_exceptions.DuplicateRequest
        json_list.append(discriminator)
    with open(REQUESTS_JSON, "w") as f:
        json.dump(json_list, f)


def check_movie_availability(movie_timestamp=0):
    " Check if a movie was requested in a range of 3.5 days "
    limit = int(time.time()) - 302400
    if movie_timestamp > limit:
        raise kino_exceptions.RestingMovie


def search_movie(films, search):
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


def get_subtitle(item):
    with open(item["subtitle"], "r") as it:
        subtitle_generator = srt.parse(it)
        return list(subtitle_generator)


# min score: 86
def find_quote(subtitle_list, words):
    logger.info("Looking for the quote: {}".format(words))
    contents = [sub.content for sub in subtitle_list]
    # Extracting 5 for debugging reasons
    final_strings = process.extract(words, contents, limit=5)
    logger.info(final_strings)
    if final_strings[0][1] < 87:
        raise kino_exceptions.NotEnoughSearchScore
    for sub in subtitle_list:
        if final_strings[0][0] == sub.content:
            final_match = {
                "message": sub.content,
                "index": sub.index,
                "start": sub.start.seconds,
                "start_m": sub.start.microseconds,
                "end_m": sub.end.microseconds,
                "end": sub.end.seconds,
                "score": final_strings[0][1],
            }
    logger.info(final_match)
    return final_match


def is_normal(quotes):
    if any(len(quote) < 2 for quote in quotes) or len(quotes) < 2 or len(quotes) > 2:
        return True


def to_dict(sub_obj=None, message=None, start=None, start_m=None, end_m=None, end=None):
    return {
        "message": sub_obj.content if sub_obj else message,
        "start": sub_obj.start.seconds if sub_obj else start,
        "start_m": sub_obj.start.microseconds if sub_obj else start_m,
        "end_m": sub_obj.end.microseconds if sub_obj else end_m,
        "end": sub_obj.end.seconds if sub_obj else end,
    }


def guess_timestamps(og_quote, quotes):
    start_sec = og_quote["start"]
    end_sec = og_quote["end"]
    start_micro = og_quote["start_m"]
    end_micro = og_quote["end_m"]
    secs = end_sec - start_sec
    extra_secs = (start_micro * 0.000001) + (end_micro * 0.000001)
    total_secs = secs + extra_secs
    quote_lengths = [len(q) for q in quotes]
    new_time = []
    for n, ql in enumerate(quote_lengths):
        percent = ((ql * 100) / len("".join(quotes))) * 0.01
        diff = total_secs * percent
        real = np.array([diff])
        inte, dec = int(np.floor(real)), (real % 1).item()
        new_micro = int(dec / 0.000001)
        new_time.append((inte, new_micro))
    return [
        to_dict(None, quotes[0], start_sec, start_micro, start_sec + 1),
        to_dict(
            None,
            quotes[1],
            new_time[0][0] + start_sec,
            new_time[1][1],
            new_time[0][0] + start_sec + 1,
        ),
    ]


def split_dialogue(subtitle):
    logger.info("Checking if the subtitle contains dialogue...")
    quote = subtitle["message"]
    quotes = quote.split("\n- ")
    if is_normal(quotes):
        quotes = quote.split("- ")
        if is_normal(quotes):
            return subtitle
    else:
        if quotes[0][:2] == "- ":
            fixed_quotes = [
                fixed.replace("- ", "") for fixed in quotes if len(fixed) > 2
            ]
            if len(fixed_quotes) == 1:
                return subtitle
            logger.info("Dialogue found")
            return guess_timestamps(subtitle, fixed_quotes)
    return subtitle


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
            lista.append(to_dict(subtitulos[index]))
            break
        else:
            lista.append(to_dict(subtitulos[index]))
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
                lista.append(to_dict(subtitulos[index]))
            else:
                break
        else:
            try:
                index += 1
                lista.append(to_dict(subtitulos[index]))
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

    return to_dict(
        None,
        pretty_quote,
        second if second else quote["start"],
        0,
        0,
        second + 1 if second else quote["end"],
    )


class Subs:
    def __init__(
        self,
        busqueda,
        words,
        movie_list,
        is_episode=False,
        multiple=False,
        replace=None,
    ):
        words = words if not replace else replace[0]
        multiple = multiple if not replace else False
        self.discriminator = None
        self.movie = search_movie(movie_list, busqueda)
        check_movie_availability(self.movie["last_request"])
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
                        self.movie["source"],
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
                        self.movie["source"],
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
            # TODO: an elegant function to handle quote loops
            logger.info("Quote request")
            subtitles = get_subtitle(self.movie)
            if not multiple and not replace:
                logger.info("Trying multiple subs")
                quotes = get_complete_quote(subtitles, words)
                multiple_quote = True if len(quotes) > 1 else False
                pils = []
                for q in quotes:
                    logger.info(q["message"])
                    split_quote = split_dialogue(q)
                    if isinstance(split_quote, list):
                        for short in split_quote:
                            pils.append(
                                get_the_kino.main(
                                    self.movie["path"],
                                    self.movie["source"],
                                    second=None,
                                    subtitle=short,
                                    gif=False,
                                    multiple=True,
                                )
                            )
                    else:
                        pils.append(
                            get_the_kino.main(
                                self.movie["path"],
                                self.movie["source"],
                                second=None,
                                subtitle=split_quote,
                                gif=False,
                                multiple=multiple_quote,
                            )
                        )
                self.pill = [random_picks.get_collage(pils, False)]
                self.discriminator = self.movie["title"] + quotes[0]["message"]
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
                            self.movie["source"],
                            second=None,
                            subtitle=new_quote,
                            gif=False,
                            multiple=False,
                        )
                    ]
                    to_dupe = new_quote["message"]
                else:
                    split_quote = split_dialogue(quote)
                    if isinstance(split_quote, list):
                        pils = []
                        for short in split_quote:
                            pils.append(
                                get_the_kino.main(
                                    self.movie["path"],
                                    self.movie["source"],
                                    second=None,
                                    subtitle=short,
                                    gif=False,
                                    multiple=True,
                                )
                            )
                        to_dupe = split_quote[0]["message"]
                        self.pill = [random_picks.get_collage(pils, False)]
                    else:
                        self.pill = [
                            get_the_kino.main(
                                self.movie["path"],
                                self.movie["source"],
                                second=None,
                                subtitle=split_quote,
                                gif=False,
                                multiple=multiple,
                            )
                        ]
                        to_dupe = split_quote["message"]
                self.discriminator = self.movie["title"] + to_dupe
            self.isminute = False
        finally:
            if self.discriminator:
                logger.info("Saving request info")
                handle_json(self.discriminator)
