#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import copy
import datetime
import logging
import os
import re
from typing import Generator, List, Optional, Sequence, Tuple, Union

import numpy as np
from pydantic import BaseModel
from pydantic import ValidationError
from pydantic import validator
from srt import Subtitle

from kinobot.constants import FONTS_DIR
import kinobot.exceptions as exceptions

from .utils import get_args_and_clean
from .utils import normalize_request_str

logger = logging.getLogger(__name__)

_DEFAULT_FONT_SIZE = 22

# This dict is hardcoded here for legacy purposes

FONTS_DICT = {
    "nfsans": os.path.join(FONTS_DIR, "NS_Medium.otf"),
    "helvetica": os.path.join(FONTS_DIR, "helvetica.ttf"),
    "helvetica-italic": os.path.join(FONTS_DIR, "helvetica-italic.ttf"),
    "clearsans": os.path.join(FONTS_DIR, "ClearSans-Medium.ttf"),
    "clearsans-regular": os.path.join(FONTS_DIR, "clearsans-regular.ttf"),
    "clearsans-italic": os.path.join(FONTS_DIR, "clearsans-italic.ttf"),
    "opensans": os.path.join(FONTS_DIR, "opensans.ttf"),
    "comicsans": os.path.join(FONTS_DIR, "comic_sans_ms.ttf"),
    "impact": os.path.join(FONTS_DIR, "impact.ttf"),
    "segoe": os.path.join(FONTS_DIR, "Segoe_UI.ttf"),
    "segoe-italic": os.path.join(FONTS_DIR, "segoe-italic.ttf"),
    "segoesm": os.path.join(FONTS_DIR, "segoe_semi_bold.ttf"),
    "papyrus": os.path.join(FONTS_DIR, "papyrus.ttf"),
    "bangers": os.path.join(FONTS_DIR, "Bangers-Regular.ttf"),
    "timesnewroman": os.path.join(FONTS_DIR, "TimesNewRoman.ttf"),
    "oldenglish": os.path.join(FONTS_DIR, "OldEnglish.ttf"),
    "segoe-bold-italic": os.path.join(FONTS_DIR, "segoe-bold-italic.ttf"),
    "tahoma": os.path.join(FONTS_DIR, "tahoma.ttf"),
    "whisper": os.path.join(FONTS_DIR, "whisper.otf"),
}

_FONT_TO_KEY_RE = re.compile(r"[\s_-]|\.[ot]tf")


def _generate_fonts(font_dir=None):
    old_values = list(FONTS_DICT.values())

    for file_ in os.listdir(font_dir or FONTS_DIR):
        if not file_.endswith((".otf", "ttf")):
            continue

        key = _FONT_TO_KEY_RE.sub("", file_).lower()
        font_path = os.path.join(FONTS_DIR, file_)

        if font_path in old_values:
            continue

        FONTS_DICT[key] = font_path


_generate_fonts()


class _ProcBase(BaseModel):
    font = "clearsans"  # "segoesm"
    font_size: float = _DEFAULT_FONT_SIZE
    font_color = "white"
    text_spacing: float = 1.0
    text_align = "center"
    y_offset = 75
    stroke_width = 0.5
    stroke_color = "black"
    palette_color_count = 10
    palette_dither = "floyd_steinberg"
    palette_colorspace: Optional[str] = None
    palette_height = 33
    palette_position = "bottom"
    palette = False
    raw = False
    no_trim = False
    ultraraw = False
    merge = False
    merge_join: Optional[str] = None
    # aspect_quotient: Optional[float] = None # Unsupported
    contrast = 20
    color = 0
    brightness = 0
    sharpness = 0
    border: Union[str, tuple, None] = None
    border_color = "white"
    text_background: Optional[str] = None
    text_shadow = 10
    text_shadow_color = "black"
    text_shadow_offset: Union[str, tuple, None] = (5, 5)
    text_shadow_blur = "boxblur"
    text_shadow_stroke = 2
    text_shadow_font_plus = 0
    zoom_factor: Optional[float] = None
    wrap_width: Optional[int] = None
    og_dict: dict = {}
    context: dict = {}
    profiles = []
    _og_instance_dict = {}

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
        allow_mutation = True

    def __init__(self, **data) -> None:
        super().__init__(**data)
        self._og_instance_dict = self.dict().copy()

    def _analize_profiles(self):
        for profile in self.profiles:
            profile.visit(self)

        self._overwrite_from_og()

    def _overwrite_from_og(self):
        for key in self.og_dict.keys():
            og_parsed_value = self._og_instance_dict.get(key)
            if og_parsed_value is None:
                continue

            logger.debug("Overwriting value from og dict: %s: %s", key, og_parsed_value)
            setattr(self, key, og_parsed_value)

    def copy(self, data):
        new_data = self.dict().copy()
        new_data.update(data)

        return _ProcBase(**new_data)

    @validator("stroke_width", "text_spacing", "text_shadow")
    @classmethod
    def _check_stroke_spacing(cls, val):
        if val > 30:
            raise exceptions.InvalidRequest(f"Dangerous value found: {val}")

        return val

    @validator("text_shadow_offset")
    def _check_shadow_offset(cls, val):
        if val is None:
            return None

        if isinstance(val, tuple):
            return val

        try:
            x_border, y_border = [int(item) for item in val.split(",")]
        except ValueError:
            raise exceptions.InvalidRequest(f"`{val}`") from None

        if any(item > 100 for item in (x_border, y_border)):
            raise exceptions.InvalidRequest("Expected `<100` value")

        return x_border, y_border

    @validator("y_offset")
    @classmethod
    def _check_y_offset(cls, val):
        if val > 500:
            raise exceptions.InvalidRequest(f"Dangerous value found: {val}")

        return val

    @validator(
        "contrast", "brightness", "color", "sharpness", "font_size", "palette_height"
    )
    @classmethod
    def _check_100(cls, val):
        if abs(val) > 100:
            raise exceptions.InvalidRequest("Values greater than 100 are not allowed")

        return val

    @validator("palette_color_count")
    @classmethod
    def _check_palette_color_count(cls, val):
        if val < 2 or val > 20:
            raise exceptions.InvalidRequest("Choose between 2 and 20")

        return val

    @validator("zoom_factor")
    @classmethod
    def _check_zoom_factor(cls, val):
        if val is None:
            return val

        if val < 1 or val > 4:
            raise exceptions.InvalidRequest("Choose between 1 and 4")

        return val

    @validator("font")
    @classmethod
    def _check_font(cls, val):
        if val not in FONTS_DICT:
            return "clearsans"

        return val

    @validator("border")
    @classmethod
    def _check_border(cls, val):
        if val is None:
            return None

        if isinstance(val, tuple):
            return val

        try:
            x_border, y_border = [int(item) for item in val.split(",")]
        except ValueError:
            raise exceptions.InvalidRequest(f"`{val}`") from None

        if any(item > 20 for item in (x_border, y_border)):
            raise exceptions.InvalidRequest("Expected `<20` value")

        return x_border, y_border


class BracketPostProc(_ProcBase):
    "Class for post-processing options for single brackets."

    remove_first = False
    remove_second = False
    plus = 0
    minus = 0
    text_wrap = 0
    x_crop_offset = 0
    y_crop_offset = 0
    no_merge = False
    wild_merge = False
    empty = False
    merge_chars = 60
    text_lines: Optional[int] = None
    append_punctuation: Optional[str] = None
    custom_crop: Union[str, list, None] = None
    split: Optional[str] = None
    total_split: Optional[str] = None
    image_url: Optional[str] = None
    image_size: Union[str, float, None] = None
    image_position: Union[str, list, None] = None
    image_rotate: Union[str, int, None] = None

    @validator("x_crop_offset", "y_crop_offset")
    @classmethod
    def _check_crop_crds(cls, val):
        if abs(val) > 100:
            raise exceptions.InvalidRequest(f"Value greater than 100 found: {val}")

        return val

    @validator("plus", "minus")
    def _check_milli(cls, val):
        if abs(val) > 10000:
            raise exceptions.InvalidRequest(f"10000ms limit exceeded: {val}")

        return val

    @validator("text_lines")
    def _check_text_lines(cls, val):
        if val is None:
            return val

        val = abs(int(val))
        if val > 30:
            raise exceptions.InvalidRequest("Text lines amount not allowed")

        return val

    @validator("append_punctuation", "merge_join")
    def _check_punct(cls, val):
        if val is None:
            return val

        if val in (".", "!", "?", "..."):
            return val

        raise exceptions.InvalidRequest("Invalid punctuation mark: %s", val)

    @validator("custom_crop")
    @classmethod
    def _check_custom_crop(cls, val):
        if val is None:
            return val

        box = _get_box(val)

        if box[0] >= box[2] or box[1] >= box[3]:
            raise exceptions.InvalidRequest(
                "The next coordinate (e.g. left -> right) can't have an "
                f"equal or lesser value: {val}"
            )

        return box

    @validator("image_position")
    @classmethod
    def _check_image_position(cls, val):
        if val is None:
            return val

        return _get_box(val, 2)

    @validator("image_rotate")
    @classmethod
    def _check_image_rotate(cls, val):
        if val is None:
            return val

        try:
            value = float(val.strip())
        except ValueError:
            return None

        if abs(value) > 360:
            raise exceptions.InvalidRequest(value)

        return value

    @validator("image_size")
    @classmethod
    def _check_image_size(cls, val):
        if val is None:
            return val

        try:
            value = float(val.strip())
        except ValueError as error:
            raise exceptions.InvalidRequest(error) from None

        if value > 3:
            raise exceptions.InvalidRequest(f"Expected =<3, found {value}")

        return value


class Bracket:
    "Class for raw brackets parsing."

    __args_tuple__ = (
        "--remove-first",
        "--remove-second",
        "--text-wrap",
        "--plus",
        "--minus",
        "--x-crop-offset",
        "--y-crop-offset",
        "--custom-crop",
        "--no-merge",
        "--wild-merge",
        "--merge-chars",
        "--empty",
        "--image-url",
        "--image-size",
        "--image-position",
        "--image-rotate",
        "--split",
        "--total-split",
        "--raw",
        "--ultraraw",
        "--font",
        "--font-color",
        "--font-size",
        "--text-spacing",
        "--text-align",
        "--y-offset",
        "--stroke-width",
        "--stroke-color",
        "--append-punctuation",
        "--text-lines",
        "--wrap-width",
        "--palette",
        "--palette-color-count",
        "--palette-colorspace",
        "--palette-dither",
        "--palette-height",
        # "--palette-position",
        "--color",
        "--contrast",
        "--brightness",
        "--sharpness",
        "--border",
        "--border-color",
        "--merge",
        "--merge-join",
        "--no-trim",
        "--text-background",
        "--text-shadow",
        "--text-shadow-color",
        "--text-shadow-offset",
        "--text-shadow-stroke",
        "--text-shadow-blur",
        "--text-shadow-font-plus",
        "--zoom-factor",
    )

    def __init__(
        self, content: str, index=None, postproc: Optional[BracketPostProc] = None
    ):
        self._content = content
        self._timestamp = True
        self._index = index or 0

        self.postproc = postproc or BracketPostProc()
        self.content: Union[str, int, tuple, Subtitle, None, List[int]] = None
        self.gif = False
        self.milli = 0

        self._load()

    @property
    def index(self):
        return self._index

    def copy(self):
        return copy.copy(self)

    def process_subtitle(self, subtitle: Subtitle) -> Sequence[Subtitle]:
        """Try to split a subtitle taking into account the post-processing
        options.

        :param subtitle:
        :type subtitle: Subtitle
        :rtype: Sequence[Subtitle]
        """
        split = self.postproc.split or self.postproc.total_split

        if split is None:
            logger.debug("Running regular process")
            return self._regular_process(subtitle)
        else:
            logger.debug("Running split process")
            return self._split_process(subtitle, split)

    def _split_process(self, subtitle: Subtitle, split=None):
        subtitle.start = datetime.timedelta(
            seconds=subtitle.start.seconds,
            microseconds=subtitle.start.microseconds + (self.milli * 1000),
        )

        total_split = self.postproc.total_split is not None

        quotes = subtitle.content.split(split)
        split = split.strip()
        new_quotes = []
        for n, quote in enumerate(quotes):
            if len(quotes) == n + 1:
                new_quotes.append(quote)
            else:
                new_quotes.append(quote.strip() + (split if not total_split else ""))

        new_quotes = [q.strip() for q in new_quotes if q.strip()]

        logger.debug("Split: %s", new_quotes)

        return _split_subtitles(subtitle, new_quotes)

    def _regular_process(self, subtitle: Subtitle) -> Sequence[Subtitle]:
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

    def update_from_swap(self, old):  # content is Subtitle
        # This class is the new (content is either Subtitle or int)
        if not isinstance(old.content, Subtitle):
            raise exceptions.InvalidRequest("Source isn't a subtitle")

        og_ = copy.copy(self)
        self.postproc = old.postproc

        mss = self.milli * 1000
        if isinstance(self.content, int):
            self.content = old.content
            self.content.start = datetime.timedelta(
                seconds=og_.content,  # type: ignore
                microseconds=mss,
            )
        else:
            self.content = old.content
            micro = og_.content.start.microseconds + mss  # type: ignore
            self.content.start = datetime.timedelta(
                seconds=og_.content.start.seconds,  # type: ignore
                microseconds=micro,
            )

    def get_indexes(self):
        return _parse_index(self.content)  # type: ignore

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
        return f"<Bracket {self.content} [{self.index}]>"


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

    return first_new, second_new


def _split_subtitles(og_quote: Subtitle, quotes: Sequence[str]) -> List[Subtitle]:

    """Guess new timestamps in order to split dialogue.

    :param og_quote:
    :type og_quote: Subtitle
    :param quotes:
    :type quotes: Sequence[str]
    """
    if len(quotes) == 1:
        return [og_quote]

    total_micros = (og_quote.end - og_quote.start) / datetime.timedelta(microseconds=1)
    new_subs = []
    last_new = None

    for new_end, q in _gen_quote_times(quotes, total_micros):
        if last_new is None:
            new_start = og_quote.start
        else:
            new_start = last_new.end

        new_ = Subtitle(
            index=og_quote.index,
            start=new_start,
            end=new_start + datetime.timedelta(microseconds=new_end),
            content=q,
        )
        new_subs.append(new_)
        last_new = new_

    return new_subs


def _gen_quote_times(
    quotes: Sequence[str], total_micro: int
) -> Generator[Tuple[int, str], None, None]:
    """Generate microseconds from quote string lengths.

    :param quotes:
    :type quotes: List[str]
    :param total_secs:
    :type total_secs: int
    :rtype: Generator[Tuple[int, int], None, None]
    """
    for quote in quotes:
        percent = ((len(quote) * 100) / len("".join(quotes))) * 0.01

        diff = total_micro * percent
        real = np.array([diff])

        inte, _ = int(np.floor(real)), (real % 1).item()

        yield inte, quote


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
    logger.debug("Checking if the subtitle contains dialogue")
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
            logger.debug("Dialogue found: %s", fixed_quotes)

            return _guess_timestamps(subtitle, fixed_quotes)

    return [subtitle]


def _get_box(val, limit=4) -> list:
    try:
        box = [int(item.strip()) for item in val.split(",")]
    except ValueError:
        raise exceptions.InvalidRequest(f"Non-int values found: {val}") from None

    if len(box) != limit:
        raise exceptions.InvalidRequest(f"Expected {limit} values, found {len(box)}")

    if any(0 < value > 100 for value in box):
        raise exceptions.InvalidRequest(
            f"Negative or greater than 100 value found: {box}"
        )

    return box


# _INDEX_RE = re.compile(r"^(?=[\d,-]*$)\b(?:(\d+-\d+)|(\d+))(?:,(?:(\d+-\d+)|(\d+)))*\b")
_INDEX_RE = re.compile(r"(\d+-\d+|\d+)(?:,|$)")
_NON_INDEX = re.compile(r"^[\d,-]*$")


def _parse_index(text: str) -> Optional[List[int]]:
    text = text.strip()
    if _NON_INDEX.search(text) is None:
        return None

    items = _INDEX_RE.findall(text)

    if not items:
        return None

    indexes = []
    for item in items:
        item = item.strip()

        if "-" in item:
            val = [int(i) for i in item.split("-")]
            if val[1] < val[0]:
                raise exceptions.InvalidRequest("Invalid range: %s", val)
            indexes.extend(range(val[0], val[1] + 1))
        else:
            indexes.append(int(item))

    return indexes
