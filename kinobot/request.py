#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import json
import logging
import re
import time

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
)
from kinobot import REQUESTS_JSON

WEBSITE = "https://kino.caretas.club"

logger = logging.getLogger(__name__)


def check_movie_availability(movie_timestamp=0):
    """
    :param movie_timestamp: last timestamp from movie dictionary
    :raises exceptions.RestingMovie
    """
    limit = int(time.time()) - 120000
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

    item = final_list[-1]
    if initial > 59:
        if raise_resting:
            check_movie_availability(item["last_request"])
        return item

    raise exceptions.MovieNotFound(
        f'Movie not found: "{query}". Maybe you meant "{item["title"]}"? '
        f"Explore the collection: {WEBSITE}."
    )


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

    raise exceptions.MovieNotFound(
        f'Episode not found: "{query}". Explore the collection: '
        f"{WEBSITE}/collection-tv."
    )


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
        raise exceptions.InvalidRequest(
            "Quote is either too short (<=2) or too long (>130)."
        )

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
    log_scores = f"(score: {final_strings[0][1]}; difference: {difference})"

    if final_strings[0][1] < 87 or difference >= 5:
        case_quote = normalize_request_str(final_strings[0][0], False)
        raise exceptions.QuoteNotFound(
            f"Quote not found: {quote} {log_scores}. "
            f'Maybe you meant "{case_quote}"? Please check the '
            f"the list of quotes on the website: {WEBSITE}"
        )

    logger.info("Good quote " + log_scores)

    for sub in subtitle_list:
        if final_strings[0][0] == sub.content:
            return to_dict(sub)


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


def de_quote_sub(text):
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
    backard_prefixes = ("-", "[", "¿", "¡")
    while True:
        if de_quote_sub(subtitle[index].content)[0].isupper() or de_quote_sub(
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
        quote = de_quote_sub(subtitle[index].content)
        if quote.endswith(forward_suffixes):
            if (
                abs(subtitle[index].end.seconds - subtitle[index + 1].start.seconds)
                >= 2
            ):
                break
            if de_quote_sub(subtitle[index + 1].content).startswith("."):
                index += 1
                sub_list.append(to_dict(subtitle[index]))
                continue
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


def unify_dialogue(subtitle_list):
    """
    Try to unify dialogues separated by index.

    :param subtitle_list: list of subtitle dictionaries
    """
    to_remove = []

    for index in range(len(subtitle_list)):
        quote = normalize_request_str(subtitle_list[index]["message"], False)
        try:
            next_quote = normalize_request_str(
                subtitle_list[index + 1]["message"], False
            )
            if (len(quote) > 30 and len(next_quote) > 25) or quote.endswith(
                ("?", "!", ":", '"')
            ):
                continue
        except IndexError:
            break

        if not quote.endswith(".") or quote.endswith(","):
            if next_quote[0].islower():
                logger.info(
                    f'Comma or inexistent dot [{index}]: "{quote} -> {next_quote}"'
                )
                subtitle_list[index + 1] = subtitle_list[index]
                subtitle_list[index + 1]["message"] = f"{quote} {next_quote}"

                to_remove.append(index)

        if quote.endswith(("...", "-")):
            if (
                next_quote.startswith(("...", "-")) or next_quote[0].islower()
            ) and re.sub(r"\...|\-", " ", next_quote).strip()[0].islower():
                logger.info(
                    f"Ellipsis or dash found with lowercase [{index}]: "
                    f'"{quote} -> {next_quote}"'
                )
                new_quote = re.sub(r"\...|\-", " ", f"{quote} {next_quote}")

                subtitle_list[index + 1] = subtitle_list[index]
                subtitle_list[index + 1]["message"] = new_quote

                to_remove.append(index)

    # Reverse the list to avoid losing the index
    for dupe_index in sorted(to_remove, reverse=True):
        del subtitle_list[dupe_index]

    return subtitle_list


def handle_json(discriminator, verified=False, on_demand=False):
    """
    Check if a quote/minute is a duplicate. If no exception is raised, append
    the quote to REQUESTS_JSON.

    :param discriminator: quote/minute info to store in REQUESTS_JSON
    :param verified: ignore already NSFW verified frames
    :param on_demand: return
    :raises exceptions.DuplicateRequest
    """
    if on_demand:
        return

    with open(REQUESTS_JSON, "r") as f:
        json_list = json.load(f)

        if not verified:
            if any(j.replace('"', "") in discriminator for j in json_list):
                raise exceptions.DuplicateRequest(
                    f"Duplicate request found with ID: {discriminator}."
                )

        json_list.append(discriminator)

    with open(REQUESTS_JSON, "w") as f:
        json.dump(json_list, f)
        logger.info(f"Requests JSON updated: {REQUESTS_JSON}")


class Request:
    def __init__(
        self,
        content,
        movie_list,
        episode_list,
        req_dictionary,
        multiple=False,
    ):
        self.on_demand = req_dictionary.get("on_demand", False)
        search_func = search_episode if req_dictionary["is_episode"] else search_movie

        raise_resting = (
            (req_dictionary["parallel"] is None)
            if not self.on_demand
            else not self.on_demand
        )

        self.movie = search_func(
            episode_list if req_dictionary["is_episode"] else movie_list,
            req_dictionary["movie"],
            raise_resting,
        )

        self.discriminator, self.chain, self.quote = None, None, None
        self.pill = []
        self.content = convert_request_content(content, return_tuple=True)
        self.req_dictionary = req_dictionary
        self.is_minute = self.content != content
        self.path = self.movie["path"]
        self.verified = req_dictionary["verified"]
        self.legacy_palette = "!palette" == self.req_dictionary["type"]
        self.multiple = multiple or self.legacy_palette

        if self.legacy_palette and len(req_dictionary["content"]) > 1:
            raise exceptions.InvalidRequest(
                "Palette requests only support one bracket."
            )

    def get_discriminator(self, text):
        if self.req_dictionary["parallel"]:
            return text[::-1]
        return text

    def handle_minute_request(self):
        # if not self.on_demand:
        #    is_valid_timestamp_request(self.req_dictionary, self.movie)

        self.pill = [
            get_final_frame(
                self.path,
                self.content[0],
                None,
                self.multiple,
                millisecond=self.content[1],
            )
        ]
        self.discriminator = f"{self.movie['title']}{self.content[0]}.{self.content[1]}"
        handle_json(
            self.get_discriminator(self.discriminator), self.verified, self.on_demand
        )

    def handle_quote_request(self):
        # TODO: an elegant function to handle quote loops
        subtitles = get_subtitle(self.movie)
        chain = guess_subtitle_chain(subtitles, self.req_dictionary)

        if isinstance(chain, list):
            self.chain = chain
            raise exceptions.ChainRequest

        quote = find_quote(subtitles, self.content)
        # parallel key == list or None
        is_parallel_ = (
            self.req_dictionary["parallel"] is not None or self.legacy_palette
        )

        if is_parallel_:
            split_quote = quote
            self.quote = split_quote["message"]
        else:
            split_quote = split_dialogue(quote)

        if isinstance(split_quote, list):
            pils = []
            for short in split_quote:
                pils.append(get_final_frame(self.path, None, short, True))
            to_dupe = split_quote[0]["message"]
            self.pill = pils
        else:
            self.pill = [
                get_final_frame(
                    self.path,
                    None,
                    split_quote,
                    # self.multiple,
                    True,
                    is_parallel_,
                )
            ]
            to_dupe = split_quote["message"]
        self.discriminator = self.movie["title"] + to_dupe
        handle_json(
            self.get_discriminator(self.discriminator), self.verified, self.on_demand
        )

    def handle_chain_request(self):
        self.discriminator = self.movie["title"] + self.chain[0]["message"]
        self.chain = unify_dialogue(self.chain)
        multiple = len(self.chain) > 1

        pils = []
        for q in self.chain:
            split_quote = split_dialogue(q)
            if isinstance(split_quote, list):
                for short in split_quote:
                    pils.append(get_final_frame(self.path, None, short, True))
            else:
                pils.append(get_final_frame(self.path, None, split_quote, multiple))
        self.pill = pils
        handle_json(self.discriminator, self.verified, self.on_demand)
