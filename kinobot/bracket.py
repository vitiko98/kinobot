#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import datetime
import logging
from typing import Generator, Sequence, Tuple, Union

import numpy as np
from pydantic import BaseModel, ValidationError, validator
from srt import Subtitle

import kinobot.exceptions as exceptions

from .utils import get_args_and_clean, normalize_request_str

logger = logging.getLogger(__name__)


class BracketPostProc(BaseModel):
    """
    Class for post-processing options for single brackets.

    Usage in request strings
    =======================
    A bracket can contain a timestamp, a quote, an index, or a range.

    An example of a functional `Bracket` would look like this:
        `[You talking to me --plus 300]`

    .. note::
        The following options are only for brackets; they don't modify the
        entire request.

    Optional arguments:

    - `--remove-first`: remove the first part of a dialogue if found

    - `--remove-second`: remove the second part of a dialogue if found

        Example:
            `[- Some question. - Some answer. --remove-first]`

        Result:
            `[Some answer.]`

    - `--plus` INT (default: 0): milliseconds to add (limit: 3000)

    - `--minus` INT (default: 0): milliseconds to subtract (limit: 3000)

        .. note::
            `--plus -30` is equal to `--minus 30`. `minus` is used for better
            readability.


    - `--x-crop-offset` INT (default: 0): relative horizontal offset for the
    cropped image (limit [-]100)

    - `--y-crop-offset` INT (default: 0): relative vertical offset for the
    cropped image (limit [-]100)

    .. note::
        `--x-crop` and `--y-crop` don't modify the final image dimensions at
        all. Their values are relative to the crop computed on the entire
        request. If the final aspect ratio doesn't modify the original
        dimensions of the images, these flags will have no effect.


    - `--custom-crop` BOX (default: None):

        A custom comma-separated list of values defining the left, upper,
        right, and lower coordinates (also known as a box) that will be
        applied to the image crop.

        As there's no way to know how many pixels an image has (different
        sources, display aspect ratio, etc.), all of the values are relative
        to the image in the scale of 0 to 100.

    .. note::
        Every time Kinobot makes a collage, all of the images are scaled to the
        same aspect ratio and resolution. In the case of multiple images,
        `--custom-crop` must be set on every bracket.


    - `--no-merge`:

        By default, Kinobot will try to merge a list of quotes by context.
        This flag will disable such behaviour.

        Take this example of a mergeable list of quotes:

            Origin: "This is a quote...", "and yes, it is a quote."

            Result: "This is a quote and yes, it is a quote."

        These quotes are being merged because Kinobot assumes they are being
        said by the same person.

        In the other hand, an example of a non-mergeable list of quotes would
        look like this:

            Origin: "Hello." "Hello there."
            Result: "Hello." "Hello there."


    - `--wild-merge`:

        Like stated on `--no-merge`, Kinobot tries to merge quotes by
        context. This flag will try to merge the quotes no matter the context
        guessed by the punctuation.

        .. warning::
            This should only be used for a list of quotes in which you are sure
            they are from the same person.

        .. todo::
            It's a known fact that the less the amount of images the better.
            The correct use of this flag will have an own Badge in the future.

    .. important::
        `--no-merge` and `--wild-merge` will only work in the first bracket
        of a request item (e.g. `!req MOVIE [CONTENT --wild-merge] [CONTENT]`)

    .. note::
        Every quote has a length limit of 60. Kinobot will gracefully ignore
        any merges if the merged length is greater than such limit.

    .. warning::
        Kinobot will raise `InvalidRequest` if any of the stated limits are
        exceeded.

    See Also:

    [Pillow documentation](https://pillow.readthedocs.io/en/stable/index.html)

    """

    remove_first = False
    remove_second = False
    plus = 0
    minus = 0
    x_crop_offset = 0
    y_crop_offset = 0
    no_merge = False
    wild_merge = False
    custom_crop: Union[str, list, None] = None

    @validator("x_crop_offset", "y_crop_offset")
    @classmethod
    def _check_crop_crds(cls, val):
        if abs(val) > 100:
            raise exceptions.InvalidRequest(f"Value greater than 100 found: {val}")

        return val

    @validator("plus", "minus")
    @classmethod
    def _check_milli(cls, val):
        if abs(val) > 3000:
            raise exceptions.InvalidRequest(f"3000ms limit exceeded: {val}")

        return val

    @validator("custom_crop")
    @classmethod
    def _check_custom_crop(cls, val):
        if val is None:
            return val

        try:
            box = [int(item.strip()) for item in val.split(",")]
        except ValueError:
            raise exceptions.InvalidRequest(f"Non-int values found: {val}") from None

        if len(box) != 4:
            raise exceptions.InvalidRequest(f"Expected 4 values, found {len(box)}")

        if any(0 < value > 100 for value in box):
            raise exceptions.InvalidRequest(
                f"Negative or greater than 100 value found: {box}"
            )

        if box[0] >= box[2] or box[1] >= box[3]:
            raise exceptions.InvalidRequest(
                "The next coordinate (e.g. left -> right) can't have an "
                f"equal or lesser value: {val}"
            )

        return box


class Bracket:
    "Class for raw brackets parsing."

    __args_tuple__ = (
        "--remove-first",
        "--remove-second",
        "--plus",
        "--minus",
        "--x-crop-offset",
        "--y-crop-offset",
        "--custom-crop",
        "--no-merge",
        "--wild-merge",
    )

    def __init__(self, content: str):
        self._content = content
        self._timestamp = True

        self.postproc = None
        self.content: Union[str, int, tuple, Subtitle, None] = None
        self.gif = False
        self.milli = 0

        self._load()

    def process_subtitle(self, subtitle: Subtitle) -> Sequence[Subtitle]:
        """Try to split a subtitle taking into account the post-processing
        options.

        :param subtitle:
        :type subtitle: Subtitle
        :rtype: Sequence[Subtitle]
        """
        subtitle.start = datetime.timedelta(
            seconds=subtitle.start.seconds,
            microseconds=subtitle.start.microseconds + (self.milli * 1000),
        )
        subtitle.content = normalize_request_str(subtitle.content, False)
        split_sub = _split_dialogue(subtitle)

        if len(split_sub) == 2:
            if self.postproc.remove_first:
                logger.debug("Removing first quote: %s", split_sub)
                return [split_sub[1]]

            if self.postproc.remove_second:
                logger.debug("Removing second quote %s", split_sub)
                return [split_sub[0]]

        return split_sub

    def is_index(self) -> bool:
        """Check if the bracket contains an index.

        :rtype: bool
        """
        if not isinstance(self.content, str):
            return False

        logger.debug("Checking for indexed content: %s", self.content)
        split_content = self.content.split("-")

        logger.debug("Looking for possible index-only request: %s", split_content)
        return not any(not index.strip().isdigit() for index in split_content)

    def _load(self):
        logger.debug("Loading bracket: %s", self._content)

        self._content, args = get_args_and_clean(self._content, self.__args_tuple__)
        try:
            self.postproc = BracketPostProc(**args)
        except ValidationError as error:
            raise exceptions.InvalidRequest(error) from None

        self._guess_type()

        if self._possible_gif_timestamp():
            self.gif = True
            self._get_gif_tuple()

        elif self._timestamp:
            self._get_timestamp()

        else:  # Quote or index
            self.content = self._content

        self.milli -= self.postproc.minus
        self.milli += self.postproc.plus

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
    start_sec = og_quote.start.seconds
    end_sec = og_quote.end.seconds
    start_micro = og_quote.start.microseconds
    end_micro = og_quote.end.microseconds

    extra_secs = (start_micro * 0.000001) + (end_micro * 0.000001)
    total_secs = end_sec - start_sec + extra_secs

    new_time = list(_gen_quote_time(quotes, total_secs))

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


def _gen_quote_time(
    quotes: Sequence[str], total_secs: int
) -> Generator[Tuple[int, int], None, None]:
    """Generate microseconds from quote string lengths.

    :param quotes:
    :type quotes: List[str]
    :param total_secs:
    :type total_secs: int
    :rtype: Generator[Tuple[int, int], None, None]
    """
    quote_lengths = [len(quote) for quote in quotes]

    for q_len in quote_lengths:
        percent = ((q_len * 100) / len("".join(quotes))) * 0.01

        diff = total_secs * percent
        real = np.array([diff])

        inte, dec = int(np.floor(real)), (real % 1).item()

        new_micro = int(dec / 0.000001)

        yield (inte, new_micro)


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
