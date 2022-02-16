#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import copy
import logging
import os
import re
from typing import Sequence

from fuzzywuzzy import process
from srt import Subtitle

import kinobot.exceptions as exceptions

from .bracket import Bracket
from .constants import LANGUAGE_SUFFIXES
from .media import hints
from .utils import normalize_request_str

_MERGE_PATTERN = re.compile(r"\...|\-")

logger = logging.getLogger(__name__)


class RequestItem:
    "Base class for an item inside a request (the Media and Bracket objects)."

    def __init__(
        self,
        media: hints,
        content: Sequence[str],
        gif: bool = False,
        language: str = "en",
    ):
        """
        :param media:
        :type media: Union[Movie, Episode, Song, YTVideo]
        :param content:
        :type content: Sequence[str]
        :param gif:
        :type gif: bool
        """
        self.media = media
        self._og_brackets = [Bracket(text) for text in content]
        self._content = [bracket.content for bracket in self._og_brackets]
        self._subtitles = []
        self._language = language
        self.gif = gif
        self.brackets = []

    def compute_brackets(self):
        "Find quotes, ranges, indexes, and timestamps."
        self._compute_brackets()

        if len(self.brackets) > 8:
            raise exceptions.InvalidRequest(
                f"Expected less than 8 frames, found {len(self.brackets)}"
            )

    @property
    def subtitle(self) -> str:
        assert self.media.path is not None

        suffix = LANGUAGE_SUFFIXES.get(self._language)
        if suffix is None:
            raise exceptions.InvalidRequest(f"Language not found: {self._language}")

        return f"{os.path.splitext(self.media.path)[0]}.{suffix}.srt"

    def _compute_brackets(self):
        if self.has_quote:
            self._subtitles = self.media.get_subtitles(self.subtitle)

        if self._is_possible_chain():
            logger.debug("Possible chain: %s", self._content)
            chain = self._guess_subtitle_chain()
            if len(chain) == len(self._content):
                # Split dialogue if needed
                for bracket, subtitle in zip(self._og_brackets, chain):
                    # self.frames.extend(bracket.process_subtitle(subtitle))
                    self._extend_brackets(bracket, subtitle)

                self._handle_merge()
            else:
                logger.debug("Invalid chain: %s", (chain, self._content))
                self._handle_mixed()
        else:
            self._handle_mixed()

    @property
    def need_palette(self) -> bool:
        return len(self.brackets) == 1

    @property
    def has_quote(self):
        return any(isinstance(bracket.content, str) for bracket in self._og_brackets)

    def _handle_indexed_bracket(self, bracket):
        split_range = bracket.content.split("-")

        if len(split_range) > 2:
            raise exceptions.InvalidRequest(
                f"Invalid start-end range: {self._content[0]}"
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
            if index > len(self._subtitles):
                raise exceptions.InvalidRequest(f"Index not found: {index}")

            self._extend_brackets(bracket, self._subtitles[index - 1])

        self._handle_merge()

    def _extend_brackets(self, bracket: Bracket, subtitle: Subtitle):
        dialogues = bracket.process_subtitle(subtitle)
        if len(dialogues) == 1:
            bracket_ = copy.copy(bracket)
            bracket_.content = dialogues[0]
            self.brackets.append(bracket_)
        else:
            first, second = copy.copy(bracket), copy.copy(bracket)
            for item, dialogue in zip((first, second), dialogues):
                item.content = dialogue
                self.brackets.append(item)

    def _handle_mixed(self):
        for bracket in self._og_brackets:
            logger.debug("Bracket: %s", bracket)
            if isinstance(bracket.content, (int, tuple)):
                self.brackets.append(bracket)
                continue

            if bracket.is_index():
                logger.debug("Index found: %s", bracket)
                self._handle_indexed_bracket(bracket)
                continue

            quote = self._find_quote(bracket.content)
            self._extend_brackets(bracket, quote)
            # self.frames.extend(bracket.process_subtitle(quote))

    def _is_possible_chain(self):
        return not any(
            isinstance(bracket.content, (int, tuple)) or bracket.is_index()
            for bracket in self._og_brackets
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

        for sub in self._subtitles:
            if normalize_request_str(quote, False) == normalize_request_str(
                sub.content, False
            ):
                logger.info("Found perfect match: %s", sub.content)
                return sub

        contents = [sub.content for sub in self._subtitles]
        # Extracting 5 for debugging reasons
        final_strings = process.extract(quote, contents, limit=3)
        # logger.info(final_strings)
        cleaned_request = normalize_request_str(quote)
        cleaned_quote = normalize_request_str(final_strings[0][0])
        difference = abs(len(cleaned_request) - len(cleaned_quote))
        log_scores = f"(score: {final_strings[0][1]}; difference: {difference})"

        if final_strings[0][1] < 87 or difference >= 5:
            case_quote = normalize_request_str(final_strings[0][0], False)
            raise exceptions.QuoteNotFound(
                f'Quote not found: {quote}. Maybe you meant "{case_quote}"? '
                f"Chek the list of quotes for this {self.media.type}: "
                f"{self.media.web_url}. Don't forget to change the language "
                " with `!lang`."
            )

        logger.info("Good quote found: %s", log_scores)

        for sub in self._subtitles:  # A better way?
            if final_strings[0][0] == sub.content:
                return sub

        raise exceptions.QuoteNotFound  # Sake of typing

    def _merge_dialogue(self, limit: int = 60):
        """
        Try to merge dialogues separated by index and grammar.

        >>> self.items = ["This is a long dialoge,", "which is separated by index"]
        >>> self._merge_dialogue()
        >>> self.items = ["This is a long dialoge which is separated by index"]
        """
        to_remove = []

        for index in range(len(self.brackets)):
            quote = self.brackets[index].content.content  # Already normalized
            if index + 1 == len(self.brackets):
                break

            next_quote = self.brackets[index + 1].content.content

            logger.debug("Quotes: %s -> %s", quote, next_quote)

            if (len(quote) + len(next_quote) > limit) or quote.endswith(
                ("?", "!", ":", '"', ";")
            ):
                continue

            if not quote.endswith(".") or quote.endswith(","):
                if next_quote[0].islower() or next_quote.endswith("."):
                    next_quote = next_quote[0].lower() + next_quote[1:]
                    logger.info(
                        f'Comma or inexistent dot [{index}]: "{quote} -> {next_quote}"'
                    )
                    self.brackets[index + 1] = self.brackets[index]
                    self.brackets[index + 1].content.content = f"{quote} {next_quote}"

                    to_remove.append(index)

            if quote.endswith(("...", "-")):
                if (
                    next_quote.startswith(("...", "-")) or next_quote[0].islower()
                ) and _MERGE_PATTERN.sub(" ", next_quote).strip()[0].islower():
                    logger.info(
                        f"Ellipsis or dash found with lowercase [{index}]: "
                        f'"{quote} -> {next_quote}"'
                    )
                    new_quote = _MERGE_PATTERN.sub(" ", f"{quote} {next_quote}")

                    self.brackets[index + 1] = self.brackets[index]
                    self.brackets[index + 1].content.content = new_quote

                    to_remove.append(index)

        self._clear_merged_brackets(to_remove)

    def _wild_merge_dialogue(self, limit: int = 60):
        """
        Try to merge dialogues separated by index.

        >>> self.items = ["This is a long dialoge.", "It has punctuation.""]
        >>> self._wild_dialogue_merge()
        >>> self.items = ["This is a long dialoge. It has punctuation"]
        """
        to_remove = []

        for index in range(len(self.brackets)):
            quote = self.brackets[index].content.content
            if index + 1 == len(self.brackets):
                break

            next_quote = self.brackets[index + 1].content.content
            if len(quote) + len(next_quote) > limit:
                continue

            self.brackets[index + 1] = self.brackets[index]
            self.brackets[index + 1].content.content = f"{quote} {next_quote}"

            to_remove.append(index)

        self._clear_merged_brackets(to_remove)

    def _clear_merged_brackets(self, to_remove):
        # Reverse the list to avoid losing the index
        for dupe_index in sorted(to_remove, reverse=True):
            logger.debug("Removing index: %d", dupe_index)
            del self.brackets[dupe_index]

    def _handle_merge(self):
        if not self._og_brackets[0].postproc.no_merge and not self._is_mixed():
            limit = self._og_brackets[0].postproc.merge_chars
            logger.debug("Merge limit: %d", limit)
            if self._og_brackets[0].postproc.wild_merge:
                self._wild_merge_dialogue(limit)
            else:
                self._merge_dialogue(limit)

    def _is_mixed(self) -> bool:
        return any(not isinstance(item.content, Subtitle) for item in self.brackets)

    def _check_perfect_chain(self) -> Sequence:
        """
        Return a list of srt.Subtitle objects if more than one coincidences
        are found.
        """
        request_list = [normalize_request_str(req) for req in self._content]  # type: ignore

        hits = 0
        index_list = []
        for subtitle in self._subtitles:
            if request_list[0] == normalize_request_str(subtitle.content):
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
            return [self._subtitles[index] for index in index_list]

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
                subtitle_ = self._subtitles[index_]
                if cleaned_content[inc] == normalize_request_str(subtitle_.content):
                    logger.debug(
                        "Appending %s index as a match was found: %s == %s",
                        index_,
                        self._content[inc],
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
        if len(self._content) == len(index_list):
            logger.debug("Perfect score: %d / %d", hits, len(self._content))

        return index_list

    def _check_chain_integrity(self, chain_list) -> bool:
        """
        Check if a list of requests strictly matchs a chain of subtitles.

        :param chain_list: list of subtitle content strings
        """
        for og_request, sub_content in zip(self._content, chain_list):
            og_len = len(normalize_request_str(og_request))  # type: ignore
            chain_len = len(normalize_request_str(sub_content))
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
        content = self._content
        content_len = len(content)

        perfect_chain = self._check_perfect_chain()
        if len(perfect_chain) == len(content):
            logger.info(
                "Found perfect chain: %s", [per.content for per in perfect_chain]
            )
            return perfect_chain

        first_quote = self._find_quote(content[0])
        first_index = first_quote.index

        chain_list = []
        for i in range(first_index - 1, (first_index + content_len) - 1):
            try:
                chain_list.append(self._subtitles[i])
            except IndexError:
                return [first_quote]

        if self._check_chain_integrity([i.content for i in chain_list]):
            return chain_list

        logger.debug("No chain found. Returning first quote found")
        return [first_quote]
