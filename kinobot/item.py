#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import datetime
import logging
import re
from typing import Sequence, Tuple, Union

import numpy as np
from fuzzywuzzy import process
from srt import Subtitle

import kinobot.exceptions as exceptions

from .media import Episode, Movie, Song  # For accurate typing
from .utils import get_args_and_clean

logger = logging.getLogger(__name__)


class RequestItem:
    """
    Base class for an item inside a request (the Media and Bracket objects).

    `Request.type Media [Bracket...]`
    """

    def __init__(
        self,
        media: Union[Movie, Episode, Song],
        content: Sequence[str],
        gif: bool = False,
    ):
        """
        :param media:
        :type media: Union[Movie, Episode, Song]
        :param content:
        :type content: Sequence[str]
        :param gif:
        :type gif: bool
        """
        self.media = media
        self.brackets = [Bracket(text) for text in content]
        self.content = [bracket.content for bracket in self.brackets]
        self.gif = gif
        self.subtitles = []
        self.frames = []
        self.capture = None

    def compute_frames(self):
        self._compute_frames()

        if len(self.frames) > 8:
            raise exceptions.InvalidRequest(
                f"Expected less than 8 frames, found {len(self.frames)}"
            )

    def _compute_frames(self):
        if self.has_quote:
            self.subtitles = self.media.get_subtitles()  # type: ignore

        if self._is_index() and isinstance(self.content[0], str):
            self._handle_indexed()
            return

        if self._is_possible_chain():
            chain = self._guess_subtitle_chain()
            if len(chain) == len(self.content):
                # Split dialogue if needed

                for bracket, subtitle in zip(self.brackets, chain):
                    self.frames.extend(bracket.process_subtitle(subtitle))

                self._unify_dialogue()
                return

        self._handle_mixed()

    @property
    def need_palette(self) -> bool:
        return len(self.frames) == 1

    @property
    def has_quote(self):
        return any(isinstance(bracket.content, str) for bracket in self.brackets)

    def _handle_indexed(self):
        for bracket in self.brackets:
            logger.debug("Handling bracket: %s", bracket)
            self._handle_indexed_bracket(bracket)

    def _handle_indexed_bracket(self, bracket):
        split_range = bracket.content.split("-")

        if len(split_range) > 2:
            raise exceptions.InvalidRequest(
                f"Invalid start-end range: {self.content[0]}"
            )
        start = int(split_range[0].strip())
        end = start + 1

        if len(split_range) > 1:
            end = int(split_range[1].strip()) + 1  # Human sintax lmao

        if start > end:
            raise exceptions.InvalidRequest(f"Negative index found: {split_range}")

        if (end - start) > 8:
            raise exceptions.InvalidRequest(
                f"Expected less than 9 items, found {end - start}"
            )

        for index in range(start, end):
            logger.debug("Appending index: %d", index)
            # self.frames.append((self.subtitles[index - 1], 0))
            if index > len(self.subtitles):
                raise exceptions.InvalidRequest(f"Index not found: {index}")

            self.frames.extend(bracket.process_subtitle(self.subtitles[index - 1]))

        self._unify_dialogue()

    def _handle_mixed(self):
        for bracket in self.brackets:
            logger.debug("Bracket: %s", bracket)
            if isinstance(bracket.content, (int, tuple)):
                self.frames.append(bracket)
                continue

            quote = self._find_quote(bracket.content)
            self.frames.extend(bracket.process_subtitle(quote))

    def _is_index(self) -> bool:
        # [x-y]
        if any(isinstance(content, (int, tuple)) for content in self.content):
            return False

        split_content = self.brackets[0].content.split("-")  # type: ignore

        logger.debug("Looking for possible index-only request: %s", split_content)

        return not any(not index.strip().isdigit() for index in split_content)

    def _is_possible_chain(self):
        return not any(
            isinstance(bracket.content, (int, tuple)) for bracket in self.brackets
        )

    def _find_quote(self, quote) -> Subtitle:
        """
        Strictly search for a quote in a list of subtitles and return a
        dictionary.

        :param subtitle_list: subtitle generator from srt
        :param quote: quote
        :raises exceptions.QuoteNotFound
        :raises exceptions.InvalidRequest
        """
        logger.debug("Looking for the quote: %s", quote)

        for sub in self.subtitles:
            if _normalize_request_str(quote, False) == _normalize_request_str(
                sub.content, False
            ):
                logger.info("Found perfect match: %s", sub.content)
                return sub

        contents = [sub.content for sub in self.subtitles]
        # Extracting 5 for debugging reasons
        final_strings = process.extract(quote, contents, limit=5)
        # logger.info(final_strings)
        cleaned_request = _normalize_request_str(quote)
        cleaned_quote = _normalize_request_str(final_strings[0][0])
        difference = abs(len(cleaned_request) - len(cleaned_quote))
        log_scores = f"(score: {final_strings[0][1]}; difference: {difference})"

        if final_strings[0][1] < 87 or difference >= 5:
            case_quote = _normalize_request_str(final_strings[0][0], False)
            raise exceptions.QuoteNotFound(
                f'Quote not found: {quote}. Maybe you meant "{case_quote}"? '
                f"Chek the list of quotes for this {self.media.type}: "
                f"{self.media.web_url}"
            )

        logger.info("Good quote found: %s", log_scores)

        for sub in self.subtitles:  # A better way?
            if final_strings[0][0] == sub.content:
                return sub

        raise exceptions.QuoteNotFound  # Sake of typing

    def _unify_dialogue(self):
        """
        Try to unify dialogues separated by index.
        """
        to_remove = []

        for index in range(len(self.frames)):
            logger.debug("Content: %s", self.frames[index])
            quote = _normalize_request_str(self.frames[index].content, False)
            if index + 1 == len(self.frames):
                break

            next_quote = _normalize_request_str(self.frames[index + 1].content, False)
            if (len(quote) > 25 and len(next_quote) > 20) or quote.endswith(
                ("?", "!", ":", '"')
            ):
                continue

            if not quote.endswith(".") or quote.endswith(","):
                if next_quote[0].islower():
                    logger.info(
                        f'Comma or inexistent dot [{index}]: "{quote} -> {next_quote}"'
                    )
                    self.frames[index + 1] = self.frames[index]
                    self.frames[index + 1].content = f"{quote} {next_quote}"

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

                    self.frames[index + 1] = self.frames[index]
                    self.frames[index + 1].content = new_quote

                    to_remove.append(index)

        # Reverse the list to avoid losing the index
        for dupe_index in sorted(to_remove, reverse=True):
            logger.debug("Removing index: %d", dupe_index)
            del self.frames[dupe_index]

    def _check_perfect_chain(self) -> Sequence:
        """
        Return a list of srt.Subtitle objects if more than one coincidences
        are found.
        """
        assert isinstance(self.subtitles, Sequence), f"Bad type: {type(self.subtitles)}"

        request_list = [_normalize_request_str(req) for req in self.content]  # type: ignore
        logger.debug("Cleaned content list to check perfect chain: %s", request_list)
        hits = 0
        index_list = []
        for subtitle in self.subtitles:
            if request_list[0] == _normalize_request_str(subtitle.content):
                logger.debug(
                    "Str match found: %s == %s", request_list[0], subtitle.content
                )
                loop_hits = self._check_sub_matches(subtitle, request_list)
                if len(loop_hits) > hits:
                    logger.debug("Good amount of hits: %d", len(loop_hits))
                    hits = len(loop_hits)
                    index_list = loop_hits

        if hits > 1:
            logger.debug("Perfect indexed chain found: %s", index_list)
            return [self.subtitles[index] for index in index_list]

        return []

    def _check_sub_matches(
        self, subtitle: Subtitle, cleaned_content: Sequence[str]
    ) -> Sequence[int]:
        """
        :param subtitle: first srt.Subtitle object reference
        :param cleaned_content: Sequence of normalized content strings
        """
        inc = 1
        hits = 1
        index_list = [subtitle.index - 1]
        while True:
            index_ = (subtitle.index + inc) - 1
            try:
                subtitle_ = self.subtitles[index_]
                if cleaned_content[inc] == _normalize_request_str(subtitle_.content):
                    logger.debug(
                        "Appending %s index as a match was found: %s == %s",
                        index_,
                        self.content[inc],
                        subtitle_.content,
                    )
                    hits += 1
                    inc += 1
                    index_list.append(index_)
                else:
                    break
            except IndexError:
                break

        logger.debug("Scores: %d -> %d", len(cleaned_content), len(index_list))
        if len(self.content) == len(index_list):
            logger.debug("Perfect score: %d / %d", hits, len(self.content))

        return index_list

    def _check_chain_integrity(self, chain_list) -> bool:
        """
        Check if a list of requests strictly matchs a chain of subtitles.

        :param chain_list: list of subtitle content strings
        """
        for og_request, sub_content in zip(self.content, chain_list):
            og_len = len(_normalize_request_str(og_request))  # type: ignore
            chain_len = len(_normalize_request_str(sub_content))
            if abs(og_len - chain_len) > 2:
                logger.debug(
                    "Check returned False from text lengths: %s -> %s",
                    og_len,
                    chain_len,
                )
                return False

        logger.debug("Good chain found: %s", chain_list)
        return True

    def _guess_subtitle_chain(self) -> Sequence[Subtitle]:
        """Try to find a subtitle chain.

        :rtype: Sequence[Subtitle]
        """
        assert self._is_possible_chain

        content = self.content
        content_len = len(content)

        perfect_chain = self._check_perfect_chain()
        if len(perfect_chain) == len(content):
            logger.info(
                "Found perfect chain: %s" % [per.content for per in perfect_chain]
            )
            return perfect_chain

        first_quote = self._find_quote(content[0])
        first_index = first_quote.index

        chain_list = []
        for i in range(first_index - 1, (first_index + content_len) - 1):
            chain_list.append(self.subtitles[i])

        if self._check_chain_integrity([i.content for i in chain_list]):
            return chain_list

        logger.debug("No chain found. Returning first quote found")
        return [first_quote]


class Bracket:
    """
    Class for post-processing options for single brackets.

    Usage in request strings
    =======================

    Syntax:
        `[BRACKET_CONTENT [--flag]]`

    where `BRACKET_CONTENT` can be a timestamp, a quote, an index, or a range.

    An example of a functional `Bracket` would look like this:
        `[You talking to me --plus 300]`

    Optional arguments:

    - `--remove-first`: remove the first part of a dialogue if found

    - `--remove-second`: remove the second part of a dialogue if found

        Example:
            `[- Some question. - Some answer. --remove-first]`

        Result:
            `[- Some answer.]`

    - `--plus` INT (default: 0): milliseconds to add (limit: 3000)

    - `--minus` INT (default: 0): milliseconds to subtract (limit: 3000)

        Example:
            `[This is a quote. --plus 300]`

        .. note::
            `--plus -30` is equal to `--minus 30`. `minus` is used for better
            readability.
        .. warning::
            Kinobot will raise `InvalidRequest` an exception if the limit is
            exceeded.
    """

    __args_tuple__ = (
        "--remove-first",
        "--remove-second",
        "--plus",
        "--minus",
    )

    def __init__(self, content: str):
        self._content = content
        self._args = {}
        self._timestamp = True

        self.content = None
        self.gif = False
        self.milli = 0

        self._load()

    def process_subtitle(self, subtitle: Subtitle) -> Sequence[Subtitle]:
        logger.debug("Milliseconds value: %s", self.milli)
        subtitle.start = datetime.timedelta(
            seconds=subtitle.start.seconds,
            microseconds=subtitle.start.microseconds + (self.milli * 1000),
        )
        logger.debug("New start: %s", subtitle.start)
        subtitle.content = _normalize_request_str(subtitle.content, False)
        split_sub = _split_dialogue(subtitle)
        logger.debug("Result: %s", [item.content for item in split_sub])
        if len(split_sub) == 2:

            if self._args.get("remove_first"):
                logger.debug("Removing first quote: %s", split_sub)
                return [split_sub[1]]

            if self._args.get("remove_second"):
                logger.debug("Removing second quote %s", split_sub)
                return [split_sub[0]]

        return split_sub

    def _load(self):
        logger.debug("Loading bracket: %s", self._content)

        self._content, self._args = get_args_and_clean(
            self._content, self.__args_tuple__
        )

        logger.debug("Loaded args: %s", self._args)

        self._guess_type()

        if self._possible_gif_timestamp():
            self.gif = True
            self._get_gif_tuple()

        elif self._timestamp:
            self._get_timestamp()

        else:  # Quote or index
            self.content = self._content

        self._milli_cheks()

    def _milli_cheks(self):
        try:
            self.milli -= self._args.get("minus", 0)
            self.milli += self._args.get("plus", 0)
        except TypeError:
            raise exceptions.InvalidRequest(
                f"Millisecond value is not an integer: {self._args}"
            ) from None

        if abs(self.milli) > 3000:
            raise exceptions.InvalidRequest("3000ms limit exceeded. Are you dumb?")

    def _guess_type(self):
        split_timestamp = self._content.split(":")

        if any(not digit.strip().isdigit() for digit in split_timestamp):
            self._timestamp = False

        # Single index requests
        if len(split_timestamp) == 1 and split_timestamp[0].strip().isdigit():
            self._timestamp = False

    def _possible_gif_timestamp(self) -> bool:
        split_content = self._content.split("-")
        logger.debug("Split: %s", split_content)

        if len(split_content) != 2:  # ! [xx:xx - xx:xx] (almost always returned)
            return False

        if len(split_content[0].strip()) != len(split_content[1].strip()):
            return False

        return split_content[1].strip()[0].isdigit() and ":" in split_content[0]

    def _get_timestamp(self):
        logger.debug("Loading timestamp info: %s", self._content)
        self.content = _get_seconds(self._content.split(":"))
        possible_milli = self._content.split(".")[-1].strip()  # "23:32.[200]"

        if possible_milli.isdigit():
            self.milli = int(possible_milli)

    def _get_gif_tuple(self):
        logger.debug("Loading GIF tuple: %s", self._content)

        tuple_ = [_get_seconds(_sec.split(":")) for _sec in self._content.split("-")]

        if len(tuple_) == 2:
            start, end = tuple_
            if (end - start) > 7:
                raise exceptions.InvalidRequest(
                    "Too long GIF request (expected less than 8 seconds)"
                )
            if start > end:
                raise exceptions.InvalidRequest("Negative range found")

            self.content = tuple(tuple_)

        else:
            raise exceptions.InvalidRequest(
                f"Invalid GIF range request: {self._content}"
            )

    def __repr__(self):
        return f"<Bracket {self.content}>"


def _get_seconds(split_timestamp: Sequence[str]) -> int:
    """
    :param split_timestamp:
    :type split_timestamp: Sequence[str]
    :raises exceptions.InvalidRequest
    """
    if len(split_timestamp) == 2:  # mm:ss
        return int(split_timestamp[0]) * 60 + int(split_timestamp[1])

    if len(split_timestamp) == 3:  # hh:mm:ss
        return (
            (int(split_timestamp[0]) * 3600)
            + (int(split_timestamp[1]) * 60)
            + int(split_timestamp[2])
        )

    raise exceptions.InvalidRequest(
        f"Invalid format: {split_timestamp}. Use mm:ss or hh:mm:ss"
    )


def _guess_timestamps(
    og_quote: Subtitle, quotes: Sequence[str]
) -> Tuple[Subtitle, Subtitle]:

    """Guess new timestamps in order to split dialogue.

    :param og_quote:
    :type og_quote: Subtitle
    :param quotes:
    :type quotes: Sequence[str]
    """
    #    temp_quote = og_quote

    start_sec = og_quote.start.seconds
    end_sec = og_quote.end.seconds
    start_micro = og_quote.start.microseconds
    end_micro = og_quote.end.microseconds

    secs = end_sec - start_sec
    extra_secs = (start_micro * 0.000001) + (end_micro * 0.000001)
    total_secs = secs + extra_secs
    quote_lengths = [len(quote) for quote in quotes]

    new_time = []

    for q_len in quote_lengths:
        percent = ((q_len * 100) / len("".join(quotes))) * 0.01
        diff = total_secs * percent
        real = np.array([diff])
        inte, dec = int(np.floor(real)), (real % 1).item()
        new_micro = int(dec / 0.000001)
        new_time.append((inte, new_micro))

    first_new = Subtitle(
        index=og_quote.index,
        start=datetime.timedelta(seconds=start_sec + 1, microseconds=0),
        end=og_quote.end,
        content=quotes[0],
    )

    index = first_new.index + 0
    content = quotes[1]
    start = datetime.timedelta(
        seconds=new_time[0][0] + start_sec, microseconds=new_time[1][1]
    )
    end = datetime.timedelta(seconds=new_time[0][0] + start_sec + 1, microseconds=0)

    second_new = Subtitle(index, start, end, content)
    logger.debug("Result: %s %s", first_new, second_new)

    return first_new, second_new


def _normalize_request_str(quote: str, lowercase: bool = True) -> str:
    quote = quote.replace("\n", " ")
    quote = re.sub(" +", " ", quote).strip()
    if lowercase:
        return quote.lower()

    return quote


def _is_normal(quotes: Sequence[str]) -> bool:
    """
    :param quotes:
    :type quotes: Sequence[str]
    """
    return any(len(quote) < 2 for quote in quotes) or len(quotes) != 2


def _split_dialogue(subtitle: Subtitle) -> Sequence[Subtitle]:
    """
    :param subtitle:
    :type subtitle: Subtitle
    """
    logger.info("Checking if the subtitle contains dialogue")
    quote = subtitle.content.replace("\n-", " -")

    quotes = quote.split(" - ")
    if _is_normal(quotes):
        quotes = quote.split(" - ")
        if _is_normal(quotes):
            return [subtitle]

    else:
        if quotes[0].startswith("- "):
            fixed_quotes = [
                fixed.replace("- ", "").strip() for fixed in quotes if len(fixed) > 2
            ]
            if len(fixed_quotes) == 1:
                return [subtitle]
            logger.info("Dialogue found: %s", fixed_quotes)

            return _guess_timestamps(subtitle, fixed_quotes)

    return [subtitle]
