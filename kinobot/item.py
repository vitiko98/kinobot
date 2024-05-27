#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import os
import re
import textwrap
from typing import Dict, List, Sequence

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
        self._og_brackets = [Bracket(text, n) for n, text in enumerate(content)]
        self._content = [bracket.content for bracket in self._og_brackets]
        self._subtitles = []
        self._language = language
        self.gif = gif
        self.brackets = []

    @property
    def og_brackets(self):
        return self._og_brackets

    def compute_brackets(self):
        "Find quotes, ranges, indexes, and timestamps."
        self._compute_brackets()

        if len(self.brackets) > 15:
            raise exceptions.InvalidRequest(
                f"Expected less than 16 frames, found {len(self.brackets)}"
            )

    def dump(self):
        return f'{self.media.dump()} {" ".join([b.dump() for b in self.og_brackets])}'

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

        self._check_text()

    def _check_text(self):
        for bracket in self.brackets:
            if isinstance(bracket.content, Subtitle):
                bracket.content.content = _normalize_quote(bracket.content.content)

    @property
    def need_palette(self) -> bool:
        return len(self.brackets) == 1

    @property
    def has_quote(self):
        return any(isinstance(bracket.content, str) for bracket in self._og_brackets)

    def _handle_indexed_bracket(self, bracket: Bracket, indexes: List[int]):
        for index in indexes:
            try:
                self._extend_brackets(bracket, self._subtitles[index - 1])
            except IndexError:
                raise exceptions.InvalidRequest(f"Index not found: {index}")

        self._handle_merge()

    def _extend_brackets(self, bracket: Bracket, subtitle: Subtitle):
        dialogues = bracket.process_subtitle(subtitle)
        if len(dialogues) == 1:
            bracket_ = bracket.copy()
            bracket_.content = dialogues[0]
            self.brackets.append(bracket_)
        else:
            for dialogue in dialogues:
                new_ = bracket.copy()
                new_.content = dialogue
                self.brackets.append(new_)

    def _handle_mixed(self):
        for bracket in self._og_brackets:
            logger.debug("Bracket: %s", bracket)
            if isinstance(bracket.content, (int, tuple)):
                self.brackets.append(bracket)
                continue

            indexes = bracket.get_indexes()
            if indexes:
                logger.debug("Indexes found: %s", indexes)
                self._handle_indexed_bracket(bracket, indexes)
                continue

            quote = self._find_quote(bracket.content)
            self._extend_brackets(bracket, quote)
            # self.frames.extend(bracket.process_subtitle(quote))

    def _is_possible_chain(self):
        return not any(
            isinstance(bracket.content, (int, tuple)) or bracket.get_indexes()
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
                f'Quote not found: {quote}. Maybe you meant "{case_quote}"?'
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
                    # Awful
                    if not next_quote.startswith("I"):
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
        self.brackets = _handle_bracket_merge(self.brackets)

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


def _handle_bracket_merge(brackets: List[Bracket]):
    groups = _group_by_index(brackets)
    logger.debug("Bracket groups by index: %s", groups)
    if not groups:
        return brackets

    for index, group in groups.items():
        if not group[0].postproc.merge:
            continue

        logger.debug("Handling wild merge for group %s", index)
        try:
            _wild_merge_dialogue(group, merge_join=group[0].postproc.merge_join)
        except AttributeError as error:
            logger.debug("Incompatible bracket found in %s: %s", group, error)

    new_brackets = []
    for items in groups.values():
        new_brackets.extend(items)

    return new_brackets


def _group_by_index(brackets) -> Dict[int, List[Bracket]]:
    groups = {}

    for bracket in brackets:
        if bracket.index not in groups:
            groups[bracket.index] = []

        groups[bracket.index].append(bracket)

    return groups


def _wild_merge_dialogue(brackets: List[Bracket], limit=None, merge_join=None):
    to_remove = []

    for index in range(len(brackets)):
        quote = brackets[index].content.content
        if index + 1 == len(brackets):
            break

        next_quote = brackets[index + 1].content.content
        if limit is not None:
            if len(quote) + len(next_quote) > limit:
                continue

        brackets[index + 1] = brackets[index]
        if merge_join is None:
            brackets[index + 1].content.content = f"{quote} {next_quote}"
        else:
            brackets[index + 1].content.content = f"{quote}{merge_join} {next_quote}"

        to_remove.append(index)

    _clear_merged_brackets(to_remove, brackets)


def _clear_merged_brackets(to_remove: List[int], brackets: List[Bracket]):
    # Reverse the list to avoid losing the index
    for dupe_index in sorted(to_remove, reverse=True):
        logger.debug("Removing index: %d", dupe_index)
        del brackets[dupe_index]


def _normalize_quote(text: str) -> str:
    """
    Adjust line breaks to correctly draw a subtitle.

    :param text: text
    """
    lines = [" ".join(line.split()) for line in text.split("\n")]
    if not lines:
        return text

    final_text = "\n".join(lines)

    if any("- " in line for line in lines):
        logger.debug("Dialogue found. Not modifying text")
        return final_text

    if len(lines) == 2:
        return final_text

    if len(lines) > 2 or (len(lines) == 1 and len(lines[0]) > 38):
        logger.debug("len(lines) >= 2 or (len(lines) == 1 and len(lines[0]) > 38) met")
        return _harmonic_wrap(final_text)

    logger.debug("Nothing to modify")
    return final_text


def _harmonic_wrap(text):
    """
    Harmonically wrap long text so it looks good on the frame.
    :param text
    """
    text_len = len(text)
    text_len_half = text_len / 2

    inc = 25
    while True:
        split_text = textwrap.wrap(text, width=inc)

        if abs(text_len - inc) < text_len_half and len(split_text) < 3:
            break

        if len(split_text) == 1 or inc > 50:
            break

        if len(split_text) != 2:
            inc += 3
            continue

        text1, text2 = split_text

        if abs(len(text1) - len(text2)) <= 5:
            logger.debug("Optimal text wrap width found: %d", inc)
            break

        inc += 3

    return "\n".join(split_text)
