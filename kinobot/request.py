#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import re
import textwrap
import time

import numpy as np
import srt
from fuzzywuzzy import fuzz, process

import kinobot.exceptions as exceptions
from kinobot.frame import clean_sub, get_final_frame
from kinobot import REQUESTS_JSON

logger = logging.getLogger(__name__)


def check_movie_availability(movie_timestamp=0):
    """
    :param movie_timestamp: last timestamp from movie dictionary
    :raises exceptions.RestingMovie
    """
    limit = int(time.time()) - 230000
    if movie_timestamp > limit:
        raise exceptions.RestingMovie


def search_movie(movie_list, query):
    """
    :param movie_list: list of dictionaries
    :param query: query
    :raises exceptions.MovieNotFound
    :raises exceptions.RestingMovie
    """
    initial = 0
    List = []

    for f in movie_list:
        title = fuzz.ratio(query, f["title"] + " " + str(f["year"]))
        ogtitle = fuzz.ratio(query, f["original_title"] + " " + str(f["year"]))
        fuzzy = title if title > ogtitle else ogtitle
        if fuzzy > initial:
            initial = fuzzy
            List.append(f)

    if initial > 59:
        check_movie_availability(List[-1]["last_request"])
        return List[-1]

    raise exceptions.MovieNotFound


def search_episode(episode_list, query):
    """
    :param episode_list: list of dictionaries
    :param query: query
    :raises exceptions.EpisodeNotFound
    :raises exceptions.RestingMovie
    """
    for ep in episode_list:
        if (
            query.lower().strip()
            == f"{ep['title']} s{ep['season']:02}e{ep['episode']:02}".lower()
        ):
            check_movie_availability(ep["last_request"])
            return ep

    raise exceptions.EpisodeNotFound


def get_subtitle(item, key="subtitle"):
    """
    :param item: movie dictionary
    :param key: key from movie dictionary
    """
    with open(item[key], "r") as it:
        subtitle_generator = srt.parse(it)
        return list(subtitle_generator)


def find_quote(subtitle_list, quote):
    """
    Strictly search for a quote in a list of subtitles and return a
    dictionary.

    :param subtitle_list: subtitle generator from srt
    :param quote: quote
    :raises exceptions.QuoteNotFound
    :raises exceptions.InvalidRequest
    """
    if len(quote) <= 2 or len(quote) > 130:
        raise exceptions.InvalidRequest

    logger.info(f"Looking for the quote: {quote}")
    contents = [sub.content for sub in subtitle_list]
    # Extracting 5 for debugging reasons
    final_strings = process.extract(quote, contents, limit=5)
    # logger.info(final_strings)
    cleaned_request = quote.replace("\n", " ").strip()
    cleaned_quote = clean_sub(final_strings[0][0].replace("\n", " ").strip())
    difference = abs(len(cleaned_request) - len(cleaned_quote))

    words = [word.lower().replace('"', "") for word in cleaned_request.split(" ")]
    words_2 = [word.lower().replace('"', "") for word in cleaned_quote.split(" ")]
    hits = 0
    for word, word_2 in zip(words, words_2):
        if word == word_2:
            hits += 1

    log_scores = (
        f"(score: {final_strings[0][1]}; diff: {difference}; "
        f"word hits: {hits}/{len(words_2)})"
    )

    if final_strings[0][1] < 87 or difference > 4 or (len(words) > 1 and hits < 2):
        logger.info("Quote not recommended " + log_scores)
        raise exceptions.QuoteNotFound

    logger.info("Good quote " + log_scores)

    for sub in subtitle_list:
        if final_strings[0][0] == sub.content:
            return {
                "message": sub.content,
                "index": sub.index,
                "start": sub.start.seconds,
                "start_m": sub.start.microseconds,
                "end_m": sub.end.microseconds,
                "end": sub.end.seconds,
                "score": final_strings[0][1],
            }

    raise exceptions.QuoteNotFound


def to_dict(sub_obj=None, message=None, start=None, start_m=None, end_m=None, end=None):
    """
    :param sub_obj: subtitle generator from srt
    :param message: message
    :param start: start
    :param start_m: start_m
    :param end_m: end_m
    :param end: end
    """
    return {
        "message": sub_obj.content if sub_obj else message,
        "start": sub_obj.start.seconds if sub_obj else start,
        "start_m": sub_obj.start.microseconds if sub_obj else start_m,
        "end_m": sub_obj.end.microseconds if sub_obj else end_m,
        "end": sub_obj.end.seconds if sub_obj else end,
    }


def guess_timestamps(og_quote, quotes):
    """
    :param og_quote: subtitle dictionary from find_quote or to_dict
    :param quotes: list of strings
    """
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


def is_normal(quotes):
    """
    :param quotes: list of strings
    """
    return any(len(quote) < 2 for quote in quotes) or len(quotes) != 2


def split_dialogue(subtitle):
    """
    :param subtitle: subtitle dictionary from find_quote or to_dict
    """
    logger.info("Checking if the subtitle contains dialogue")
    quote = subtitle["message"].replace("\n-", " -")
    quotes = quote.split(" - ")
    if is_normal(quotes):
        quotes = quote.split(" - ")
        if is_normal(quotes):
            return subtitle
    else:
        if quotes[0].startswith("- "):
            fixed_quotes = [
                fixed.replace("- ", "").strip() for fixed in quotes if len(fixed) > 2
            ]
            if len(fixed_quotes) == 1:
                return subtitle
            logger.info("Dialogue found")
            return guess_timestamps(subtitle, fixed_quotes)
    return subtitle


def cleansub(text):
    return clean_sub(text).replace('"', "")


def get_complete_quote(subtitle, quote):
    """
    Find a subtitle dictionary and try to detect the context of a the line.
    If "context" is found, append subtitle dictionaries before or after the line.

    :param subtitle: subtitle generator from srt
    :param quote: quote string to search for
    """
    final = find_quote(subtitle, quote)
    if 0 == final["index"]:
        return [final]
    if len(subtitle) == final["index"]:
        return [final]

    initial_index = final["index"] - 1
    index = initial_index
    sub_list = []

    # Backward
    backard_prefixes = ("-", "[")
    while True:
        if cleansub(subtitle[index].content)[0].isupper() or cleansub(
            subtitle[index].content
        ).startswith(backard_prefixes):
            sub_list.append(to_dict(subtitle[index]))
            break

        sub_list.append(to_dict(subtitle[index]))

        if abs(subtitle[index].start.seconds - subtitle[index - 1].end.seconds) >= 2:
            break

        index = index - 1

    sub_list.reverse()
    index = initial_index
    # Forward
    forward_suffixes = (".", "]", "!", "?")
    while True:
        quote = cleansub(subtitle[index].content)
        if quote.endswith(forward_suffixes):
            if (
                abs(subtitle[index].end.seconds - subtitle[index + 1].start.seconds)
                >= 2
            ):
                break
            if cleansub(subtitle[index + 1].content).startswith("."):
                index += 1
                sub_list.append(to_dict(subtitle[index]))
            else:
                break
        else:
            try:
                index += 1
                sub_list.append(to_dict(subtitle[index]))
            except IndexError:
                break

    if len(sub_list) > 3:
        return [final]

    logger.info(f"Context found from {len(sub_list)} quotes")
    return sub_list


def replace_request(new_words="Hello", second=None, quote=None):
    """
    :param new_words: new words to replace the old subtitle
    :param second: second
    :param quote: subtitle dictionary
    """
    if len(new_words) > 80 or len(new_words) < 4:
        raise TypeError

    text = textwrap.fill(new_words, 40)

    def uppercase(matchobj):
        return matchobj.group(0).upper()

    def capitalize(s):
        return re.sub(r"^([a-z])|[\.|\?|\!]\s*([a-z])|\s+([a-z])(?=\.)", uppercase, s)

    pretty_quote = capitalize(text)
    logger.info(f"Cleaned new quote: {pretty_quote}")

    return to_dict(
        None,
        pretty_quote,
        second if second else quote["start"],
        0,
        0,
        second + 1 if second else quote["end"],
    )


def handle_json(discriminator):
    """
    Check if a quote/minute is a duplicate. If no exception is raised, append
    the quote to REQUESTS_JSON.

    :param discriminator: quote/minute info to store in REQUESTS_JSON
    :raises exceptions.DuplicateRequest
    """
    with open(REQUESTS_JSON, "r") as f:
        json_list = json.load(f)
        if any(j.replace('"', "") in discriminator for j in json_list):
            raise exceptions.DuplicateRequest
        json_list.append(discriminator)
    with open(REQUESTS_JSON, "w") as f:
        json.dump(json_list, f)
        logger.info(f"Requests JSON updated: {REQUESTS_JSON}")


class Request:
    def __init__(
        self,
        query,
        content,
        movie_list,
        episode_list,
        multiple=False,
        is_episode=False,
    ):
        if is_episode:
            self.movie = search_episode(episode_list, query)
        else:
            self.movie = search_movie(movie_list, query)

        self.discriminator = None
        self.content = self.clean_request(content)
        self.is_minute = self.content != content
        self.query = query
        self.multiple = multiple
        self.is_web = "web" in self.movie["source"].lower()
        self.pill = []

    def clean_request(self, content):
        try:
            try:
                m, s = content.split(":")
                second = int(m) * 60 + int(s)
            except ValueError:
                h, m, s = content.split(":")
                second = (int(h) * 3600) + (int(m) * 60) + int(s)
            logger.info(f"Time request found (second {second})")
            return second
        except ValueError:
            logger.info("Quote request found")
            return content

    def handle_minute_request(self):
        self.pill = [
            get_final_frame(
                self.movie["path"], self.content, None, self.multiple, self.is_web
            )
        ]
        self.discriminator = f"{self.query}{self.content}"
        handle_json(self.discriminator)

    def handle_quote_request(self):
        # TODO: an elegant function to handle quote loops
        subtitles = get_subtitle(self.movie)
        if not self.multiple:
            logger.info("Trying multiple subs")
            quotes = get_complete_quote(subtitles, self.content)
            multiple_quote = len(quotes) > 1
            pils = []
            for q in quotes:
                split_quote = split_dialogue(q)
                if isinstance(split_quote, list):
                    for short in split_quote:
                        pils.append(
                            get_final_frame(
                                self.movie["path"], None, short, True, self.is_web
                            )
                        )
                else:
                    pils.append(
                        get_final_frame(
                            self.movie["path"],
                            None,
                            split_quote,
                            multiple_quote,
                            self.is_web,
                        )
                    )
            self.pill = pils
            self.discriminator = self.movie["title"] + quotes[0]["message"]
        else:
            logger.info("Trying multiple subs")
            quote = find_quote(subtitles, self.content)
            split_quote = split_dialogue(quote)
            if isinstance(split_quote, list):
                pils = []
                for short in split_quote:
                    pils.append(
                        get_final_frame(
                            self.movie["path"], None, short, True, self.is_web
                        )
                    )
                to_dupe = split_quote[0]["message"]
                self.pill = pils
            else:
                self.pill = [
                    get_final_frame(
                        self.movie["path"],
                        None,
                        split_quote,
                        self.multiple,
                        self.is_web,
                    )
                ]
                to_dupe = split_quote["message"]
            self.discriminator = self.movie["title"] + to_dupe
        handle_json(self.discriminator)
