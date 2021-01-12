#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import re
import textwrap
import time

from operator import itemgetter
from random import shuffle

import numpy as np
from fuzzywuzzy import fuzz, process

import kinobot.exceptions as exceptions
from kinobot.frame import get_final_frame
from kinobot.utils import (
    convert_request_content,
    clean_sub,
    get_subtitle,
    normalize_request_str,
    check_chain_integrity,
    check_perfect_chain,
    is_valid_timestamp_request,
    HOUR,
    POPULAR,
)
from kinobot import REQUESTS_JSON

logger = logging.getLogger(__name__)


def check_movie_availability(movie_timestamp=0):
    """
    :param movie_timestamp: last timestamp from movie dictionary
    :raises exceptions.RestingMovie
    """
    limit = int(time.time()) - 150000
    if movie_timestamp > limit:
        raise exceptions.RestingMovie


def search_movie(movie_list, query, raise_resting=True):
    """
    :param movie_list: list of dictionaries
    :param query: query
    :param raise_resting: raise an exception for resting movies
    :raises exceptions.MovieNotFound
    :raises exceptions.RestingMovie
    """
    query = query.lower()

    initial = 0
    final_list = []
    for f in movie_list:
        title = fuzz.ratio(query, f"{f['title']} {f['year']}".lower())
        ogtitle = fuzz.ratio(query, f"{f['original_title']} {f['year']}".lower())
        fuzzy = title if title > ogtitle else ogtitle
        if fuzzy > initial:
            initial = fuzzy
            final_list.append(f)

    if initial > 59:
        if raise_resting:
            check_movie_availability(final_list[-1]["last_request"])
        return final_list[-1]

    raise exceptions.MovieNotFound


def search_episode(episode_list, query, raise_resting=True):
    """
    :param episode_list: list of dictionaries
    :param query: query
    :param raise_resting: raise an exception for resting episodes
    :raises exceptions.EpisodeNotFound
    :raises exceptions.RestingMovie
    """
    for ep in episode_list:
        if (
            query.lower().strip()
            == f"{ep['title']} s{ep['season']:02}e{ep['episode']:02}".lower()
        ):
            if raise_resting:
                check_movie_availability(ep["last_request"])
            return ep

    raise exceptions.EpisodeNotFound


def rotate_requests_by_hour(movie_list, request_list):
    """
    :param movie_list: list of movie dictionaries
    :param request_list: list of request dictionaries
    """
    request_list = request_list[:500]
    logger.info("Rotating requests")

    final_list = []
    for request in request_list:
        try:
            movie = search_movie(movie_list, request["movie"])
        except (exceptions.MovieNotFound, exceptions.RestingMovie):
            continue
        final_list.append({"request": request, "popularity": movie["popularity"]})

    popular = HOUR in POPULAR

    logger.info(f"Filter by popular hour: {popular}")

    rotated = sorted(final_list, key=itemgetter("popularity"), reverse=popular)
    rotated_1, rotated_2 = rotated[:75], rotated[75:]

    shuffle(rotated_1)

    return [request["request"] for request in rotated_1 + rotated_2]


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

    for sub in subtitle_list:
        if normalize_request_str(quote, False) == normalize_request_str(
            sub.content, False
        ):
            logger.info("Found perfect match")
            return to_dict(sub)

    contents = [sub.content for sub in subtitle_list]
    # Extracting 5 for debugging reasons
    final_strings = process.extract(quote, contents, limit=5)
    # logger.info(final_strings)
    cleaned_request = normalize_request_str(quote)
    cleaned_quote = normalize_request_str(final_strings[0][0])
    difference = abs(len(cleaned_request) - len(cleaned_quote))
    log_scores = f"(score: {final_strings[0][1]}; diff: {difference})"

    if final_strings[0][1] < 87 or difference >= 2:
        logger.info("Quote not recommended " + log_scores)
        raise exceptions.QuoteNotFound

    logger.info("Good quote " + log_scores)

    for sub in subtitle_list:
        if final_strings[0][0] == sub.content:
            return to_dict(sub)

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
        "index": sub_obj.index if sub_obj else 0,
    }


def guess_subtitle_chain(subtitle_list, req_dictionary):
    """
    :param subtitle_list: list of srt.Subtitle objects
    :param req_dictionary: request comment dictionary
    """
    content = req_dictionary["content"]
    req_dictionary_length = len(content)

    if (
        any(isinstance(convert_request_content(req_), int) for req_ in content)
        or req_dictionary_length == 1
    ):
        return

    perfect_chain = check_perfect_chain(content, subtitle_list)
    if len(perfect_chain) == len(content):
        logger.info("Found perfect chain: %s" % [per.content for per in perfect_chain])
        return [to_dict(chain) for chain in perfect_chain]

    first_quote = find_quote(subtitle_list, content[0])
    first_index = first_quote["index"]

    chain_list = []
    for i in range(first_index - 1, (first_index + req_dictionary_length) - 1):
        chain_list.append(to_dict(subtitle_list[i]))

    try:
        check_chain_integrity(content, [i["message"] for i in chain_list])
        logger.info(f"Chain request found: {req_dictionary_length} quotes")
        return chain_list
    except exceptions.InconsistentSubtitleChain:
        return


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
    for ql in quote_lengths:
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
    if 0 == final["index"] or len(subtitle) == final["index"] - 1:
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


def handle_json(discriminator, verified=False):
    """
    Check if a quote/minute is a duplicate. If no exception is raised, append
    the quote to REQUESTS_JSON.

    :param discriminator: quote/minute info to store in REQUESTS_JSON
    :param verified: ignore already NSFW verified frames
    :raises exceptions.DuplicateRequest
    """
    if verified:
        logger.info("Test not needed")
        return

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
        req_dictionary,
        multiple=False,
        is_episode=False,
    ):
        if is_episode:
            self.movie = search_episode(episode_list, query)
        else:
            self.movie = search_movie(movie_list, query)

        self.discriminator, self.chain = None, None
        self.content = convert_request_content(content)
        self.req_dictionary = req_dictionary
        self.is_minute = self.content != content
        self.query = query
        self.multiple = multiple
        self.dar = self.movie.get("dar")
        self.path = self.movie.get("path")
        self.pill = []

    def handle_minute_request(self):
        is_valid_timestamp_request(self.req_dictionary, self.movie)
        self.pill = [
            get_final_frame(self.path, self.content, None, self.multiple, self.dar)
        ]
        self.discriminator = f"{self.query}{self.content}"
        handle_json(self.discriminator, self.req_dictionary["verified"])

    def handle_quote_request(self):
        # TODO: an elegant function to handle quote loops
        subtitles = get_subtitle(self.movie)
        chain = guess_subtitle_chain(subtitles, self.req_dictionary)

        if isinstance(chain, list):
            self.chain = chain
            raise exceptions.ChainRequest

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
                            get_final_frame(self.path, None, short, True, self.dar)
                        )
                else:
                    pils.append(
                        get_final_frame(
                            self.path,
                            None,
                            split_quote,
                            multiple_quote,
                            self.dar,
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
                    pils.append(get_final_frame(self.path, None, short, True, self.dar))
                to_dupe = split_quote[0]["message"]
                self.pill = pils
            else:
                self.pill = [
                    get_final_frame(
                        self.path, None, split_quote, self.multiple, self.dar
                    )
                ]
                to_dupe = split_quote["message"]
            self.discriminator = self.movie["title"] + to_dupe
        handle_json(self.discriminator, self.req_dictionary["verified"])

    def handle_chain_request(self):
        self.discriminator = self.movie["title"] + self.chain[0]["message"]
        pils = []
        for q in self.chain:
            split_quote = split_dialogue(q)
            if isinstance(split_quote, list):
                for short in split_quote:
                    pils.append(get_final_frame(self.path, None, short, True, self.dar))
            else:
                pils.append(
                    get_final_frame(self.path, None, split_quote, True, self.dar)
                )
        self.pill = pils
        handle_json(self.discriminator, self.req_dictionary["verified"])
