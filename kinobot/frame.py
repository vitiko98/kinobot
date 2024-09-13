#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import datetime
from functools import cached_property
import logging
import os
from pprint import pprint
import re
import textwrap
from typing import Any, Generator, List, Optional, Sequence, Tuple, Union
import uuid

from cv2 import cv2
import numpy as np
from PIL import Image
from PIL import ImageDraw
from PIL import ImageEnhance
from PIL import ImageFilter
from PIL import ImageFont
from PIL import ImageOps
from PIL import ImageStat
from PIL import UnidentifiedImageError
from pydantic import BaseModel
from pydantic import ValidationError
from pydantic import validator
from srt import Subtitle

from kinobot import profiles
import kinobot.exceptions as exceptions
from kinobot.playhouse.lyric_card import make_card

from . import request_trace
from .bracket import Bracket
from .config import config
from .constants import CACHED_FRAMES_DIR
from .constants import FRAMES_DIR
from .constants import IMAGE_EXTENSION
from .item import RequestItem
from .media import Episode
from .media import hints
from .media import Movie
from .palette import draw_palette_from_config
from .palette import LegacyPalette
from .palette import Palette
from .profiles import Profile
from .story import Story
from .utils import download_image

_UPPER_SPLIT = re.compile(r"(\s*[.!?♪\-]\s*)")
_STRANGE_RE = re.compile(r"[^a-zA-ZÀ-ú0-9?!\.\ \¿\?',&-_*(\n)]")
_BAD_DOTS = re.compile(r"(?u)\.{2,}")
_STYLE = re.compile(r"<.*?>")
_EXTRA_SPACE = re.compile(" +")

_REPLACEMENTS = (
    (_STYLE, ""),
    # (_STRANGE_RE, ""),
    # (_BAD_DOTS, "..."),
    (_EXTRA_SPACE, " "),
)

_POSSIBLES = {
    1: (1, 1),
    2: (1, 2),
    3: (1, 3),
    4: (1, 4),
}

_VALID_COLLAGES = [
    (1, 2),
    (1, 3),
    (2, 1),
    (2, 2),
    (1, 4),
    (1, 5),
    (2, 3),
    (2, 4),
    (3, 3),
]
_LATERAL_COLLAGES = [(2, 1), (2, 2), (2, 3), (2, 4)]

_DEFAULT_FONT_SIZE = 22

FONTS_DIR = config.fonts_dir

# TODO: generate this dict automatically from the fonts directory

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

_DEFAULT_FONT = os.path.join(FONTS_DIR, "helvetica.ttf")


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

logger = logging.getLogger(__name__)


class Frame:
    """Class for single frames with intended post-processing."""

    def __init__(self, media: hints, bracket: Bracket, pp=None):
        self.media = media
        self.bracket = bracket
        self.message: Union[str, None] = None

        content = self.bracket.content
        if isinstance(content, Subtitle):
            self.seconds = content.start.seconds
            self.milliseconds = content.start.microseconds / 1000
            self.message = content.content  # Subtitle message
        elif isinstance(content, int):
            self.seconds = content
            self.milliseconds = bracket.milli
        else:
            raise exceptions.InvalidRequest("Frames must contain quotes or timestamps")

        self._pp = pp or PostProc()
        self._cv2: np.ndarray
        self.pil: Image.Image
        self.finished_quote: Optional[str] = None

    def load_frame(self):
        "Load the cv2 array and the PIL image object."
        if self._is_cached():
            self._load_pil_from_cv2()
        else:
            self._cv2 = self.media.get_frame((self.seconds, self.milliseconds))

            if not self._pp.no_trim:
                self._cv2_trim()

            self._load_pil_from_cv2()

            self._cache_image()

    def make_trace(self) -> request_trace.Frame:
        data = dict()

        data["text"] = self.finished_quote
        data["dimensions"] = self.pil.size
        data["timestamp"] = datetime.timedelta(seconds=1)
        data["media_uri"] = "foo://123"  # TODO
        data["postproc"] = (self._pp or PostProc()).dict()

        return request_trace.Frame(**data)

    def load_palette(self, classic: bool = True):
        palette_cls = Palette if classic else LegacyPalette

        if classic and self.grayscale:
            logger.info("Grayscale image found. Ignoring palette draw")
        else:
            palette = palette_cls(self.pil, discriminator=self.discriminator)
            palette.draw()
            self.pil = palette.image

    @property
    def pretty_content(self) -> str:
        if self.message is not None:
            return self.message  # Subtitle message

        return str(datetime.timedelta(seconds=self.seconds))  # hh:mm:ss

    @property
    def is_timestamp(self) -> bool:
        return isinstance(self.bracket.content, int)

    @cached_property
    def grayscale(self) -> bool:
        hsv = ImageStat.Stat(self.pil.convert("HSV"))
        return hsv.mean[1] < 35

    @cached_property
    def discriminator(self) -> str:
        prefix = f"{self.media.type}_{self.media.id}_nt_{self._pp.no_trim}"
        return f"{prefix}_{self.seconds}_{self.milliseconds}.{IMAGE_EXTENSION}"

    def _cache_image(self):
        image_path = os.path.join(CACHED_FRAMES_DIR, self.discriminator)
        logger.info("Caching image: %s", image_path)

        self.pil.save(image_path)

    def _is_cached(self) -> bool:
        image_path = os.path.join(CACHED_FRAMES_DIR, self.discriminator)
        if os.path.isfile(image_path) and os.path.getsize(image_path) >= 2048:
            logger.info("Nothing to do. Cached image found: %s", self.discriminator)
            self._cv2 = cv2.imread(image_path)
            return True

        return False

    def _load_pil_from_cv2(self):
        self.pil = _pretty_scale(_load_pil_from_cv2(self._cv2), 1920)

    def _cv2_trim(self) -> bool:
        """
        Remove black borders from a cv2 image array.

        This method is a fucking waste of time as most sources are already
        properly cropped. We need to use it because of a few shitty WEB sources.
        Fucking unbelievable.

        :param cv2_image: cv2 image array
        """
        logger.info("Trying to remove black borders with cv2")
        og_w, og_h = self._cv2.shape[1], self._cv2.shape[0]
        logger.debug("Original dimensions: %dx%d", og_w, og_h)
        og_quotient = og_w / og_h

        first_img = _remove_lateral_cv2(self._cv2)

        tmp_img = cv2.transpose(first_img)
        tmp_img = cv2.flip(tmp_img, flipCode=1)

        if tmp_img is None:
            raise exceptions.InvalidRequest("Possible all-black image found")

        final = _remove_lateral_cv2(tmp_img)

        out = cv2.transpose(final)

        final_img = cv2.flip(out, flipCode=0)
        if final_img is None:
            raise exceptions.InvalidRequest("Possible all-black image found")

        new_w, new_h = final_img.shape[1], final_img.shape[0]

        logger.debug("New dimensions: %dx%d", new_w, new_h)
        new_quotient = new_w / new_h

        if abs(new_quotient - og_quotient) > 0.9:
            logger.info(
                "Possible bad quotient found: %s -> %s", og_quotient, new_quotient
            )
            return False

        width_percent = (100 / og_w) * new_w
        height_percent = (100 / og_h) * new_h

        if any(percent <= 65 for percent in (width_percent, height_percent)):
            logger.info(
                "Possible bad trim found: %s -> %s", width_percent, height_percent
            )
            return False

        self._cv2 = final_img
        return True

    def __repr__(self):
        return f"<Frame: {self.media} - {self.pretty_content}>"


class GIF:
    """Class for GIF requests with minimal post-processing."""

    def __init__(
        self,
        media: Union[Movie, Episode],
        content_list,
        id: str,
    ):
        raise NotImplementedError

    @property
    def title(self) -> str:
        raise NotImplementedError

    @classmethod
    def from_request(cls, request):
        raise NotImplementedError

    def get(self, path: Optional[str] = None) -> List[str]:  # Consistency
        raise NotImplementedError


class PostProc(BaseModel):
    "Class for post-processing options applied in an entire request."

    frame: Optional[Frame] = None
    font: str = "clearsans"  # "segoesm"
    font_size: float = _DEFAULT_FONT_SIZE
    font_color: str = "white"
    text_spacing: float = 1.0
    text_align: str = "center"
    y_offset: int = 15
    stroke_width: float = 0.5
    stroke_color: str = "black"
    palette_color_count: int = 10
    palette_dither: str = "floyd_steinberg"
    palette_colorspace: Optional[str] = None
    palette_height: int = 33
    palette_position: str = "bottom"
    palette: bool = False
    mirror: bool = False
    mirror_after: bool = False
    raw: bool = False
    no_trim: bool = False
    ultraraw: bool = False
    no_collage: bool = False
    dimensions: Union[None, str, tuple] = None
    aspect_quotient: Optional[float] = None
    contrast: int = 20
    color: int = 0
    brightness: int = 0
    sharpness: int = 0
    tint: Optional[str] = None
    tint_alpha: float = 0.5
    wrap_width: Optional[int] = None
    glitch: Union[str, dict, None] = None
    apply_to: Union[str, tuple, None] = None
    border: Union[str, tuple, None] = None
    border_color: str = "white"
    text_background: Optional[str] = None
    text_shadow: int = 10
    text_shadow_color: str = "black"
    text_shadow_offset: Union[str, tuple, None] = (5, 5)
    text_xy: Union[str, tuple, None] = None
    text_shadow_blur: str = "boxblur"
    text_shadow_stroke: int = 2
    text_shadow_font_plus: int = 0
    zoom_factor: Optional[float] = None
    flip: Optional[str] = None
    no_collage_resize: bool = False
    static_title: Optional[str] = None
    og_dict: dict = {}
    context: dict = {}
    debug: bool = False
    debug_color: Optional[str] = None
    profiles: List = []
    _og_instance_dict: dict = {}

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
        allow_mutation = True

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        self._og_instance_dict = self.dict().copy()

    def _analize_profiles(self):
        if not self.profiles:
            logger.debug("No profiles to analize")
            return None
        else:
            for profile in self.profiles:
                profile.visit(self)

        self._overwrite_from_og()

    def process(
        self, frame: Frame, draw: bool = True, only_crop: bool = False, no_debug=False
    ) -> Image.Image:
        """Process a frame and return a PIL Image object.

        :param frame:
        :type frame: Frame
        :param draw:
        :type draw: bool
        :param only_crop:
        :type only_crop: bool
        :rtype: Image.Image
        """
        logger.debug("Processing frame: %s", frame)
        self.frame = frame

        self._analize_profiles()

        self.raw = self.ultraraw or self.raw

        if not self.raw:
            self._crop()
            if not only_crop:
                self._pil_enhanced()

        self._analize_profiles()

        if draw and not self.ultraraw:
            self._draw_quote()

        if not no_debug and self.debug:
            info = self.dict(exclude_unset=True).copy()
            info.update(self.frame.bracket.postproc.dict(exclude_unset=True))
            self.frame.pil = _get_debug(
                self.frame.pil, info, grid_color=info.get("debug_color")
            )

        if self.palette:
            self.frame.pil = draw_palette_from_config(self.frame.pil, **self.dict())

        return self.frame.pil

    def _mirror_image(self, img: Image.Image, flip: str):
        if flip is None:
            logger.debug("Nothing to flip")
            return img

        if flip == "right":
            return img.transpose(Image.FLIP_LEFT_RIGHT)
        elif flip == "bottom":
            return img.transpose(Image.FLIP_TOP_BOTTOM)
        else:
            logger.info("Unsupported flip")

        return img

    def _overwrite_from_og(self):
        for key in self.og_dict.keys():
            og_parsed_value = self._og_instance_dict.get(key)
            if og_parsed_value is None:
                continue

            logger.debug("Overwriting value from og dict: %s: %s", key, og_parsed_value)
            setattr(self, key, og_parsed_value)

    def pixel_intensity(self):
        if self.frame is None or self.frame.message is None:
            return None

        quote = self.frame.message.split("\n")[0]
        text_box = _get_text_area_box(self.frame.pil, quote, **self.dict())
        logger.debug("Text area box: %s", text_box)
        return _get_white_level(self.frame.pil.crop(text_box))

    def copy(self, data):
        new_data = self.dict().copy()
        new_data.update(data)

        return PostProc(**new_data)

    def process_list(self, frames: List[Frame] = None) -> List[Image.Image]:
        """Handle a list of frames, taking into account the post-processing
        flags.

        :param frames:
        :type frames: List[Frame]
        :rtype: List[Image.Image]
        """
        frames = frames or []

        self._image_list_check(frames)

        apply_to = self.apply_to or tuple(range(len(frames)))

        logger.debug("Index list to apply post-processing: %s", apply_to)
        pils = []
        for index, frame in enumerate(frames):
            only_crop = not index in apply_to  # type: ignore
            pils.append(
                self.process(frame, draw=False, only_crop=only_crop, no_debug=True)
            )

        if not self.no_collage_resize:
            pils = _homogenize_images(pils)

        assert len(pils) == len(frames)

        if not self.ultraraw:  # Don't even bother
            for n, pil, frame in zip(range(len(pils)), pils, frames):
                if frame.message is not None:
                    config_ = self.dict().copy()
                    config_.update(frame.bracket.postproc.dict(exclude_unset=True))

                    quote = _prettify_quote(
                        _clean_sub(frame.message),
                        wrap_width=config_.get("wrap_width"),
                        text_lines=config_.get("text_lines"),
                    )
                    frame.finished_quote = quote

                    _draw_quote(pil, quote, **config_)

                    if config_.get("debug"):
                        debug_ = self.dict(exclude_unset=True).copy()
                        debug_.update(frame.bracket.postproc.dict(exclude_unset=True))

                        self.no_collage = True
                        debugged = _get_debug(
                            pil, debug_, grid_color=debug_.get("debug_color")
                        )
                        pils[n] = debugged

        if self.no_collage or (self.dimensions is None and len(frames) > 4):
            return pils

        collage = Collage(pils, self.dimensions)  # type: ignore
        if self.border is not None:
            collage.add_borders(self.border, self.border_color)  # type: ignore

        return [collage.get()]

    def _image_list_check(self, frames):
        if (
            self.dimensions is not None
            and len(frames) != (self.dimensions[0] * self.dimensions[1])  # type: ignore
            and self.no_collage is False
        ):
            raise exceptions.InvalidRequest(
                f"Kinobot returned {len(frames)} frames; such amount is compatible"
                f" with the requested collage dimensions: {self.dimensions}"
            )

        logger.debug("Requested dimensions: %s", self.dimensions)

        if self.dimensions is None:
            self.dimensions = _POSSIBLES.get(len(frames))  # Still can be None

        if (
            self.dimensions is not None
            and self.dimensions in _LATERAL_COLLAGES
            and self.font_size == _DEFAULT_FONT_SIZE
        ):
            self.font_size += 2

        logger.debug("Found dimensions: %s", self.dimensions)

    _enhance = {
        "contrast": ImageEnhance.Contrast,
        "brightness": ImageEnhance.Brightness,
        "sharpness": ImageEnhance.Sharpness,
        "color": ImageEnhance.Color,
    }

    def _pil_enhanced(self):
        config_ = self.dict().copy()
        config_.update(self.frame.bracket.postproc.dict(exclude_unset=True))

        for key, cls_ in self._enhance.items():
            value = config_[key]
            if not value:
                continue

            value = 1 + value * 0.01
            logger.debug("Applying %s: %s", key, value)
            instance = cls_(self.frame.pil)
            self.frame.pil = instance.enhance(value)

        # Fixme
        if config_["zoom_factor"]:
            self.frame.pil = _zoom_img(self.frame.pil, config_["zoom_factor"])

        self.frame.pil = self._mirror_image(self.frame.pil, config_.get("flip"))

        if config_.get("mirror"):
            self.frame.pil = _funny_mirror(self.frame.pil)

        if config_.get("tint"):
            self.frame.pil = _tint_image(
                self.frame.pil, config_["tint"], config_.get("tint_alpha", 0.5)
            )

    def _draw_quote(self):
        if self.frame.message is not None:
            config_ = self.dict().copy()
            config_.update(self.frame.bracket.postproc.dict(exclude_unset=True))

            quote = _prettify_quote(
                _clean_sub(self.frame.message),
                wrap_width=config_.get("wrap_width"),
                text_lines=config_.get("text_lines"),
            )
            self.frame.finished_quote = quote

            _draw_quote(self.frame.pil, quote, **config_)

            if config_.get("mirror_after"):
                self.frame.pil = _funny_mirror(self.frame.pil)

    def _crop(self):
        custom_crop = self.frame.bracket.postproc.custom_crop
        if custom_crop is not None:
            self.frame.pil = _scaled_crop(
                self.frame.pil, custom_crop, self.frame.bracket.postproc.no_scale
            )

        if self.frame.bracket.postproc.image_url is not None:
            self._handle_paste(self.frame)  # type: ignore

        elif self.aspect_quotient is not None:
            x_off = self.frame.bracket.postproc.x_crop_offset
            y_off = self.frame.bracket.postproc.y_crop_offset

            self.frame.pil = _crop_by_threshold(
                self.frame.pil,
                self.aspect_quotient,
                x_off=x_off,
                y_off=y_off,
                custom_crop=custom_crop,
            )

    @staticmethod
    def _handle_paste(frame: Frame):
        image, non_transparent = _get_from_image_url(
            frame.bracket.postproc.image_url.strip("<>")
        )
        size = image.size

        og_image = frame.pil
        image.thumbnail((og_image.size))

        logger.debug("Url image size: %s", size)

        resize = frame.bracket.postproc.image_size or 1
        rotate = frame.bracket.postproc.image_rotate

        position = frame.bracket.postproc.image_position or [0, 0]
        if frame.bracket.postproc.no_scale is False:
            position = (
                int(og_image.size[0] * (position[0] / 100)),  # type: ignore
                int(og_image.size[1] * (position[1] / 100)),  # type: ignore
            )

        if resize != 1:
            logger.debug("Resizing image: %s * %s", size, resize)
            image = image.resize((int(size[0] * resize), int(size[1] * resize)))

        if rotate:
            logger.debug("Rotating image: %s", rotate)
            image = image.rotate(int(rotate))

        logger.debug("Pasting image: %s", position)
        if non_transparent is False:
            frame.pil.paste(image, position, image)
        else:
            frame.pil.paste(image, position)

    @validator("stroke_width", "text_spacing", "text_shadow")
    @classmethod
    def _check_stroke_spacing(cls, val):
        if val > 30:
            raise exceptions.InvalidRequest(f"Dangerous value found: {val}")

        return val

    @validator("y_offset")
    @classmethod
    def _check_y_offset(cls, val):
        if val > 500:
            raise exceptions.InvalidRequest(f"Dangerous value found: {val}")

        return val

    @validator("zoom_factor")
    @classmethod
    def _check_zoom_factor(cls, val):
        if val is None:
            return val

        if val < 1 or val > 4:
            raise exceptions.InvalidRequest("Choose between 1 and 4")

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

    @validator("aspect_quotient")
    @classmethod
    def _check_ap(cls, val):
        if val is None:
            return None

        if 1 > val < 2.5:
            raise exceptions.InvalidRequest(f"Expected 1>|<2.5, found {val}")

        return val

    @validator("font")
    @classmethod
    def _check_font(cls, val):
        if val not in FONTS_DICT:
            return "clearsans"

        return val

    @validator("dimensions")
    @classmethod
    def _check_dimensions(cls, val):
        if val is None:
            return None

        if isinstance(val, tuple):
            return val

        values = [number.strip() for number in val.split("x")]

        if len(values) != 2 or any(not val.isdigit() for val in values):
            raise exceptions.InvalidRequest(f"Invalid dimensions: {val}")

        values = int(values[0]), int(values[1])

        if values not in _VALID_COLLAGES:
            raise exceptions.InvalidRequest(
                f"Invalid collage. Choose between: `{_VALID_COLLAGES}`"
            )

        logger.debug("Found dimensions value: %s", values)
        return values

    @validator("glitch")
    @classmethod
    def _check_glitch(cls, val):
        # --glitch glitch_amount=3,color_offset=True,scan_lines=True
        if val is None:
            return None

        glitch_dict = {"glitch_amount": 4, "color_offset": True, "scan_lines": True}

        fields = val.split(",")
        for field in fields:
            field_split = field.split("=")
            key = field_split[0]

            if key not in glitch_dict:
                continue

            if len(field_split) != 2:
                raise exceptions.InvalidRequest(f"`{field_split}`")

            if key == "glitch_amount":
                try:
                    value = abs(int(field_split[-1]))
                    if value > 10:
                        raise exceptions.InvalidRequest("Expected <10") from None
                except ValueError:
                    raise exceptions.InvalidRequest("Expected integer") from None
                glitch_dict["glitch_amount"] = value or 1
            else:
                glitch_dict[key] = "true" in field_split[-1].lower()

        logger.debug("Updated glitch dict: %s", glitch_dict)
        return glitch_dict

    @validator("apply_to")
    @classmethod
    def _check_apply_to(cls, val):
        if not val:  # Falsy
            return None

        if isinstance(val, tuple):
            return val

        range_ = val.split("-")
        try:
            if len(range_) == 1:  # --apply-to x
                num = int(range_[0].split(".")[0])
                final = tuple(range(num - 1, num))
            else:  # --apply-to x-x
                final = tuple(range(int(range_[0]) - 1, int(range_[1])))
        except ValueError:
            raise exceptions.InvalidRequest(f"`{range_}`") from None

        logger.debug("Parsed apply to: %s", final)
        return final

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

    @validator("text_shadow_offset", "text_xy")
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
            pass
            # raise exceptions.InvalidRequest("Expected `<100` value")

        return x_border, y_border


def _tint_image(img: Image.Image, tint_color, alpha=0.5):
    image = img.convert("RGBA")

    tint = Image.new("RGBA", image.size, tint_color)

    blended_image = Image.blend(image, tint, alpha=alpha)

    return blended_image.convert("RGB")


def _funny_mirror(img: Image.Image):
    width, height = img.size

    left_half = img.crop((0, 0, width // 2, height))

    right_half = left_half.transpose(Image.FLIP_LEFT_RIGHT)

    width_left, height_left = left_half.size

    width_right, height_right = right_half.size

    new_width = width_left + width_right
    new_height = max(height_left, height_right)
    combined_image = Image.new("RGB", (new_width, new_height))

    combined_image.paste(left_half, (0, 0))

    combined_image.paste(right_half, (width_left, 0))

    return combined_image


class Static:
    """Class for static requests with advanced post-processing."""

    def __init__(self, items: Sequence[RequestItem], type_: str, id_: str, **kwargs):
        self.items = items
        self.id: str = id_
        self.type: str = type_

        self.frames: List[Frame] = []

        self._paths = []

        try:
            self.postproc = PostProc(**kwargs)
        except ValidationError as error:
            raise exceptions.InvalidRequest(error) from None

        self._raw: Optional[Image.Image] = None
        self._request_trace = None

    @classmethod
    def from_request(cls, request):
        custom_profiles = request.args.get("custom_profiles")
        if custom_profiles is None:
            profiles_path = config.profiles_path
        else:
            profiles_path = os.path.join(
                os.path.dirname(config.profiles_path or ""), custom_profiles
            )

        try:
            profiles_ = profiles.Profile.from_yaml_file(profiles_path)
        except (TypeError, FileNotFoundError) as error:
            logger.error(
                "Couldn't load profiles from file: %s (%s)", profiles_path, error
            )
            profiles_ = []

        return cls(
            request.items,
            request.type,
            request.id,
            **request.args,
            og_dict=request.args,
            profiles=profiles_,
        )

    def get(self, path: Optional[str] = None) -> List[str]:
        """Load and get the image paths for the request.

        :param path:
        :type path: Optional[str]
        :rtype: List[str]
        """
        path = path or os.path.join(FRAMES_DIR, str(self.id))

        os.makedirs(path, exist_ok=True)

        logger.debug("Request folder created: %s", path)

        self._load_frames()

        self.postproc.context.update({"frame_count": len(self.frames)})

        single_img = os.path.join(path, f"00.{IMAGE_EXTENSION}")
        self._paths.append(single_img)

        if len(self.frames) == 1:
            logger.debug("Single static image found: %s", single_img)

            frame = self.frames[0]
            palette = self.type == "!palette"
            image = self.postproc.process(frame, draw=not palette)

            if palette:
                palette = LegacyPalette(image)
                palette.draw()
                image = palette.image

            image.save(single_img)

        else:
            images = self.postproc.process_list(self.frames)

            if len(images) == 1:
                images[0].save(single_img)
            else:
                self._paths.pop(0)
                for num, image in enumerate(images):
                    path_ = os.path.join(path, f"{num:02}.{IMAGE_EXTENSION}")
                    image.save(path_)
                    self._paths.append(path_)

        logger.debug("Final paths: %s", self._paths)

        return self._paths

    def make_trace(self) -> request_trace.RequestTrace:
        data = dict()
        data["frames"] = [frame.make_trace() for frame in self.frames]
        data["single_image"] = len(self._paths) == 1
        data["command"] = self.type
        data["postproc"] = self.postproc.dict()
        data["postproc_raw"] = self.postproc.dict(exclude_unset=True)

        return request_trace.RequestTrace(**data)

    @property
    def initial_item(self) -> RequestItem:
        """Initial item of a RequestItem list (always used for non-parallel
        requests).

        :rtype: RequestItem
        """
        return self.items[0]

    @cached_property
    def story(self) -> Story:
        """Story object ready to get images. Takes only the first media item
        for parallel requests.

        :rtype: Story
        """
        assert len(self._paths) > 0
        return Story(self.initial_item.media, self._paths[0], raw=self._raw)

    @property
    def content(self) -> str:
        """The content string of the frames.

        Example:
            TIMESTAMP | QUOTE

        :rtype: str
        """
        return " | ".join(frame.pretty_content for frame in self.frames)

    @property
    def title(self) -> str:
        """The title of the handler.

        Examples:
            MOVIE (YEAR) dir. DIRECTOR
            Category: CATEGORY

            MOVIE (YEAR) | EPISODE
            Category: Kinema Parallels

        :rtype: str
        """
        if self.postproc.static_title is not None:
            return self.postproc.static_title

        logger.debug("Type: %s", self.type)
        if self.type == "!parallel":
            header = self._get_parallel_header()
            if " | " in header:  # Ensure that the request is a parallel
                return "\n".join((header, self._category_str()))

        header = self.initial_item.media.pretty_title
        sub = ""

        if self.initial_item.media.metadata is not None:
            sub = self.initial_item.media.metadata.request_title

        return "\n".join((header, sub))

    @property
    def images(self) -> List[str]:  # Consistency
        "List of generated image paths."
        return self._paths

    def _category_str(self) -> str:
        if any(item.media.type != "movie" for item in self.items):
            return "Category: Art Parallels"

        return "Category: Kinema Parallels"

    def _load_frames(self):
        logger.debug("Items: %s", self.items)
        for request in self.items:
            request.compute_brackets()

            for frame in request.brackets:
                frame_ = Frame(request.media, frame, self.postproc)
                frame_.load_frame()

                logger.debug("Appending frame: %s", frame_)

                self.frames.append(frame_)

        if not self.frames:
            raise exceptions.NothingFound("No valid frames found")

        # For stories
        self._raw = self.frames[0].pil

        logger.debug("Loaded frames: %s", len(self.frames))

    def _get_parallel_header(self) -> str:
        titles = [item.media.parallel_title for item in self.items]
        # Remove dupes
        return " | ".join(list(dict.fromkeys(titles)))

    def __repr__(self) -> str:
        return f"<Static ({len(self.items)} items)>"


class Card(Static):
    "Class for the swap handler."

    def __init__(self, items: Sequence[RequestItem], type_: str, id_: str, **kwargs):
        super().__init__(items, type_, id_, **kwargs)
        self.type = "!parallel"  # Temporary

        if len(self.items) != 2:
            raise exceptions.InvalidRequest("Expected only two media items")

        self._lyrics_item = None
        self._generic_item = None
        self._lyrics = ""

        for item in items:
            if item.media.type == "lyrics":
                self._lyrics_item = item
            else:
                self._generic_item = item

        if self._lyrics_item is None:
            raise exceptions.InvalidRequest("No lyics media item set")

    def _load_frames(self):
        logger.debug("Items: %s", self.items)
        self._lyrics_item.compute_brackets()  # type: ignore

        lyrics = []
        for bracket in self._lyrics_item.brackets:
            lyrics.append(bracket.content.content.replace("\n", " ").strip())

        self._lyrics = "\n".join(lyrics)

        self._generic_item.compute_brackets()  # type: ignore

        for frame in self._generic_item.brackets:
            frame_ = Frame(self._generic_item.media, frame, self.postproc)
            frame_.load_frame()

            logger.debug("Appending frame: %s", frame_)

            self.frames.append(frame_)

        if not self.frames:
            raise exceptions.NothingFound("No valid frames found")

        # For stories
        self._raw = self.frames[0].pil

        logger.debug("Loaded frames: %s", len(self.frames))

    @property
    def title(self):
        if self._generic_item.media.type in ("song", "cover"):
            titles = str(self._lyrics_item.media)
        else:
            titles = (
                f"{self._lyrics_item.media} | {self._generic_item.media.simple_title}"
            )

        return f"{titles}\nCategory: Lyrics Cards"

    def get(self, path: Optional[str] = None) -> List[str]:
        image = super().get(path)[0]

        title = f"{self._lyrics_item.media.simple_title} | {self._generic_item.media.simple_title}"
        if len(title) > 70:
            title = f"{self._lyrics_item.media.simple_title}\n{self._generic_item.media.simple_title}"

        if self._generic_item.media.type in ("song", "cover"):
            title = self._lyrics_item.media.simple_title

        lyrics_font = os.path.join(FONTS_DIR, "programme_light.otf")
        title_font = os.path.join(FONTS_DIR, "Programme-Regular.ttf")

        make_card(
            Image.open(image),
            title.upper(),
            self._lyrics,
            lyrics_font=lyrics_font,
            title_font=title_font,
        ).save(image)

        return [image]


class Swap(Static):
    "Class for the swap handler."

    def __init__(self, items: Sequence[RequestItem], type_: str, id_: str, **kwargs):
        super().__init__(items, type_, id_, **kwargs)
        self.type = "!parallel"  # Temporary

    def _load_frames(self):
        if len(self.items) != 2:
            raise exceptions.InvalidRequest("Expected 2 items for swap")

        ids = [item.media.id for item in self.items]
        if ids[0] == ids[1]:
            raise exceptions.InvalidRequest("Can't swap the same movie")

        brackets = self._get_brackets()

        # Just left the last media item
        temp_item = self.items[-1]
        sliced = np.array_split(brackets, 2)

        source, dest = sliced
        for old, new in zip(source, dest):
            if not new.postproc.empty and not old.postproc.keep:
                new.update_from_swap(old)
            else:
                logger.debug("Ignoring swap for bracket: %s", new)

            if old.postproc.keep:
                logger.debug("Keeping source: %s", old)
                frame_ = Frame(self.items[0].media, old, self.postproc)
                frame_.load_frame()
            else:
                frame_ = Frame(temp_item.media, new, self.postproc)
                frame_.load_frame()

            logger.debug("Appending frame: %s", frame_)

            self.frames.append(frame_)

        # For stories
        self._raw = self.frames[0].pil

        logger.debug("Loaded frames: %s", len(self.frames))

    def _get_brackets(self):
        brackets = []
        brackets_len = None

        logger.debug("Brackets len: %s", brackets_len)

        for request in self.items:
            request.compute_brackets()

            new_len = len(request.brackets)

            if brackets_len is None:
                brackets_len = new_len

            elif new_len != brackets_len:
                msg = f"Inconsistent amount of frames: {brackets_len} -> {new_len}"
                if brackets_len != new_len:
                    raise exceptions.InvalidRequest(msg)

                brackets_len = new_len

            brackets.extend(request.brackets)

        return brackets

    def _category_str(self) -> str:
        if any(item.media.type != "movie" for item in self.items):
            return "Category: Art Swapped Parallels"

        return "Category: Kinema Swapped Parallels"


def _scaled_crop(image: Image.Image, custom_crop, no_scale):
    if no_scale is False:
        width, height = image.size
        box = _scale_from_100(custom_crop, width, height)
        logger.debug("Generated custom box: %s", box)
        return image.crop(box)

    return image.crop(custom_crop)


def _crop_by_threshold(
    image: Image.Image, threshold: float = 1.65, **kwargs
) -> Image.Image:
    width, height = image.size
    init_w, init_h = width, height
    quotient = width / height
    inc = 0
    limit = 500

    while True:
        inc += 1
        if quotient > threshold:
            width -= 7
            quotient = (width - (init_w - width)) / init_h
            crop_tuple = (init_w - width, 0, width, init_h)
        else:
            height -= 7
            off = init_h - height
            quotient = init_w / (init_h - off)
            crop_tuple = (0, off / 2, init_w, init_h - (off / 2))

        if abs(quotient - threshold) < 0.03:
            crop_tuple = list(crop_tuple)

            # Doing the logic here to avoid making operations on every loop
            if kwargs.get("x_off"):
                total_removed = crop_tuple[0]
                offset = total_removed * (kwargs["x_off"] / 100)
                crop_tuple[0], crop_tuple[2] = (
                    crop_tuple[0] + offset,
                    crop_tuple[2] + offset,
                )

            if kwargs.get("y_off"):
                total_removed = crop_tuple[1]
                offset = total_removed * (kwargs["y_off"] / 100)
                crop_tuple[1], crop_tuple[3] = (
                    crop_tuple[1] - offset,
                    crop_tuple[3] - offset,
                )

            crop_tuple = tuple(crop_tuple)
            logger.debug("Final quotient and crop tuple: %s - %s", quotient, crop_tuple)
            logger.debug("Total loops: %d", inc)
            return image.crop(crop_tuple)

        if inc > limit:
            raise NotImplementedError(
                f"An infinite loop was prevented: {init_w}/{init_w}"
            )


def _scale_from_100(box: list, width: int, height: int) -> tuple:
    left = width * (box[0] / 100)
    upper = height * (box[1] / 100)
    right = width * (box[2] / 100)
    lower = height * (box[3] / 100)

    return (left, upper, right, lower)


def _crop_image(image: Image.Image, new_width=720, new_height=480) -> Image.Image:
    width, height = image.size

    left = (width - new_width) / 2
    right = (width + new_width) / 2
    top = (height - new_height) / 2
    bottom = (height + new_height) / 2

    return image.crop((int(left), int(top), int(right), int(bottom)))


def _thumbnail_images(images: List[Image.Image]):
    """
    :param images: list of PIL.Image objects
    """
    sizes = [image.size for image in images]

    for image in images:
        if image.size != min(sizes):
            image.thumbnail(min(sizes))
        yield image


def _homogenize_images(images: List[Image.Image]) -> list:
    """
    :param images: list of PIL.Image objects
    """
    images = list(_thumbnail_images(images))

    first_min = min([image.size for image in images], key=lambda t: t[0])
    second_min = min([image.size for image in images], key=lambda t: t[1])

    return [_crop_image(image, first_min[0], second_min[1]) for image in images]


def _fix_dar(cv2_image, dar: float):
    """
    Fix aspect ratio from cv2 image array.
    """
    logger.debug("Fixing image with DAR: %s", dar)

    width, height = cv2_image.shape[:2]

    # fix width
    fixed_aspect = dar / (width / height)
    width = int(width * fixed_aspect)
    # resize with fixed width (cv2)
    return cv2.resize(cv2_image, (width, height))


def _draw_quote(image: Image.Image, quote: str, modify_text: bool = True, **kwargs):
    scale = kwargs.get("font_size", 27.5) * 0.001
    font_size = int((image.size[0] * scale) + (image.size[1] * scale))
    logger.debug("Guessed font size: %s", font_size)
    y_offset = kwargs.get("y_offset", 15)

    lines_count = len(quote.split("\n"))

    if lines_count > 1:
        text_height = _get_text_height(image, quote.split("\n")[0], **kwargs)
        to_add = _get_percentage_of(text_height, image.size[1]) * lines_count

        new_y_offset = y_offset + ((to_add / lines_count) * (lines_count - 1))

        logger.debug("New y offset: %s -> %s", y_offset, new_y_offset)

        kwargs.update({"y_offset": new_y_offset})

    plus_y = 0

    for line in quote.split("\n"):
        plus_y += __draw_quote(image, line, plus_y=plus_y, **kwargs)


def _get_text_height(image, quote, **kwargs):
    font = FONTS_DICT.get(kwargs.get("font", "")) or _DEFAULT_FONT
    draw = ImageDraw.Draw(image)

    width, height = image.size

    scale = kwargs.get("font_size", 27.5) * 0.001

    font_size = int((width * scale) + (height * scale))
    font = ImageFont.truetype(font, font_size)

    _, txt_h = draw.textsize(quote, font)  # type: ignore
    return txt_h


def _get_text_area_box(image, quote, **kwargs):
    font = FONTS_DICT.get(kwargs.get("font", "")) or _DEFAULT_FONT
    draw = ImageDraw.Draw(image)

    width, height = image.size

    scale = kwargs.get("font_size", 27.5) * 0.001

    font_size = int((width * scale) + (height * scale))
    font = ImageFont.truetype(font, font_size)

    off = _get_percentage(kwargs.get("y_offset", 15), height)

    txt_w, txt_h = draw.textsize(quote, font)  # type: ignore
    txt_h = font_size

    draw_h = height - txt_h - off
    x1 = (width - txt_w) / 2

    # return _TextAreaData(x1=x1, y1=draw_h, x2=x1 + txt_w, y2=draw_h + txt_h)
    return (x1, draw_h, x1 + txt_w, draw_h + txt_h)


def _get_percentage_of(value, total):
    return int((value / total) * 100)


def _get_percentage(percentage, total) -> int:
    return int((percentage / 100) * total)


def __draw_quote(image: Image.Image, quote: str, plus_y=0, **kwargs):
    """Draw a quote into a PIL Image object.

    :param image:
    :type image: Image.Image
    :param quote:
    :type quote: str
    :param kwargs:
        * font
        * font_size
        * font_color
        * text_spacing
        * text_align
        * y_offset
        * stroke_width
        * stroke_color
        * text_background
    """
    font = FONTS_DICT.get(kwargs.get("font", "")) or _DEFAULT_FONT
    draw = ImageDraw.Draw(image)

    text_xy = kwargs.get("text_xy")
    logger.debug("About to draw quote: %s (font: %s)", quote, font)

    width, height = image.size
    logger.debug("Width, height: %s", (width, height))

    scale = kwargs.get("font_size", 27.5) * 0.001

    font_size = int((width * scale) + (height * scale))
    font = ImageFont.truetype(font, font_size)

    off = _get_percentage(kwargs.get("y_offset", 15), height)
    logger.debug("Offset: %s", off)

    txt_w, txt_h = draw.textsize(quote, font)
    txt_h = font_size

    draw_h = height - txt_h - off
    if kwargs.get("text_background"):
        kwargs["stroke_width"] = 0
        x = (width - txt_w) / 2
        div = draw_h * 0.033  # IDK
        y = draw_h + div
        box = (x, y - div, x + txt_w, y + txt_h)
        draw.rectangle(box, fill=kwargs["text_background"])

    stroke_width = 0
    logger.debug((txt_w, txt_h))
    logger.debug(
        (((width - txt_w) / 2), draw_h + plus_y),
    )

    if kwargs.get("text_shadow"):
        blurred = Image.new("RGBA", image.size)
        draw_1 = ImageDraw.Draw(blurred)
        offset = [int(i) for i in kwargs.get("text_shadow_offset", (5, 5))]

        stroke_width = int(kwargs.get("text_shadow_stroke", 2))
        if not text_xy:
            box_ = (((width - txt_w) / 2) + offset[0], draw_h + offset[1] + plus_y)
        else:
            box_ = text_xy[0] + offset[0], text_xy[1] + offset[1] + plus_y

        draw_1.text(
            box_,
            quote,
            kwargs.get("text_shadow_color", "black"),
            font=font,
            align=kwargs.get("text_align", "center"),
            spacing=kwargs.get("text_spacing", 0.8),
            stroke_width=stroke_width,
            stroke_fill=kwargs.get("stroke_color", "black"),
        )
        blur_type = kwargs.get("text_shadow_blur", "boxblur")

        if blur_type == "gaussian":
            blurred = blurred.filter(ImageFilter.GaussianBlur(kwargs["text_shadow"]))
        else:
            blurred = blurred.filter(ImageFilter.BoxBlur(kwargs["text_shadow"]))

        image.paste(blurred, blurred)

    if not text_xy:
        draw_box = (width - txt_w) / 2, draw_h + plus_y
    else:
        draw_box = text_xy[0], text_xy[1] + plus_y

    draw.text(
        # ((width - txt_w) / 2, draw_h),
        draw_box,
        quote,
        kwargs.get("font_color", "white"),
        font=font,
        align=kwargs.get("text_align", "center"),
        spacing=kwargs.get("text_spacing", 0.8),
        stroke_width=int(width * (kwargs.get("stroke_width", 3) * 0.001)),
        stroke_fill=kwargs.get("stroke_color", "black"),
    )
    return txt_h


def _load_pil_from_cv2(cv2_img: np.ndarray):
    """
    Convert an array to a PIL.Image object.
    """
    image = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB)
    return Image.fromarray(image)


# A better way?
def _scale_to_gif(frame) -> np.ndarray:
    """Scale an image to make it suitable for GIFs."

    :param frame:
    :rtype: np.ndarray
    """
    w, h = frame.shape[1], frame.shape[0]
    inc = 0.5
    while True:
        if w * inc < 600:
            break
        inc -= 0.1

    return cv2.resize(frame, (int(w * inc), int(h * inc)))


def _prettify_quote(text: str, wrap_width=None, text_lines=None) -> str:
    """
    Adjust line breaks to correctly draw a subtitle.

    :param text: text
    """
    lines = [" ".join(line.split()) for line in text.split("\n")]
    if not lines:
        return text

    final_text = "\n".join(lines)

    if text_lines is not None:
        logger.debug("Running wrap based on %s text lines", text_lines)
        param = len(final_text) // text_lines
        return _harmonic_wrap(text, param, param)

    if wrap_width is not None:
        logger.debug("Using wrap width: %s", wrap_width)
        return textwrap.fill(final_text, width=wrap_width)

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


def __justify(txt: str, width: int) -> str:
    # https://stackoverflow.com/a/66087666
    prev_txt = txt
    while (l := width - len(txt)) > 0:
        txt = re.sub(r"(\s+)", r"\1 ", txt, count=l)
        if txt == prev_txt:
            break
    return txt.rjust(width)


def _handle_text_justify(text: str, wrap_width=30, text_len_diff_tolerancy=10):
    text = text.replace("\n", " ")

    wrapper = textwrap.TextWrapper(width=wrap_width)
    dedented_text = textwrap.dedent(text=text)

    txt = wrapper.fill(text=dedented_text)

    for l in txt.splitlines():
        print(__justify(l, wrap_width // 2))


def __prettify_quote(text: str) -> str:
    """
    Adjust line breaks to correctly draw a subtitle.

    :param text: text
    """
    lines = [" ".join(line.split()) for line in text.split("\n")]
    final_text = "\n".join(lines)

    if len(lines) == 2 and not any("-" in line for line in lines):
        # if abs(len(lines[0]) - len(lines[1])) > 30:
        final_text = _harmonic_wrap(final_text.replace("\n", " "))

    if (len(lines) == 1 and len(text) > 35) or len(lines) > 2:
        final_text = _harmonic_wrap(final_text)

    if len(re.findall("-", final_text)) == 1 and final_text.startswith("-"):
        final_text = final_text.replace("-", "").strip()

    return final_text


def _harmonic_wrap(text, limit=50, start=25):
    """
    Harmonically wrap long text so it looks good on the frame.
    :param text
    """
    text_len = len(text)
    text_len_half = text_len / 2

    inc = start
    while True:
        split_text = textwrap.wrap(text, width=inc)

        if abs(text_len - inc) < text_len_half and len(split_text) < 3:
            break

        if len(split_text) == 1 or inc > limit:
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


def _remove_lateral_cv2(cv2_image):
    """
    :param cv2_image: cv2 image array
    """
    width = cv2_image.shape[1]

    checks = 0
    for i in range(width):
        if np.mean(cv2_image[:, i, :]) > 1.7:
            break
        checks += 1

    for j in range(width - 1, 0, -1):
        if np.mean(cv2_image[:, j, :]) > 1.7:
            break
        checks += 1

    if checks < 10:
        return cv2_image  # Why even bother copying?

    return cv2_image[:, i : j + 1, :].copy()  # type: ignore


def _clean_sub(text: str) -> str:
    """
    Remove unwanted characters from a subtitle string.

    :param text: text
    """
    logger.debug("About to clean subtitle: %s", text)

    for replacement in _REPLACEMENTS:
        logger.debug("Using %s replacement. Og text: %s", replacement[0], text)
        text = re.sub(replacement[0], replacement[1], text)

    logger.debug("Result: %s", text)
    return text.strip()


def _pretty_scale(image: Image.Image, min_w=1500):
    if image.size[0] >= min_w:
        logger.debug("Image already met %s requirement: %s", min_w, image.size)
        return image

    to_scale = min_w / image.size[0]
    new_size = tuple(int(item * to_scale) for item in image.size)
    logger.debug("Scaling to new size: %s", new_size)
    return image.resize(new_size)


class Collage:
    "Class for image collages with support for borders and multiple dimensions."

    def __init__(
        self,
        images: List[Image.Image],
        dimensions: Optional[Tuple[int, int]] = None,
    ):
        self._images = images
        self._dimensions = dimensions or _POSSIBLES[len(images)]
        self._lateral = self._dimensions in _LATERAL_COLLAGES
        self._border_x: Optional[int] = None
        self._border_y: Optional[int] = None
        self._color: Optional[str] = None

    @property
    def lateral(self) -> bool:
        return self._dimensions in _LATERAL_COLLAGES

    def add_borders(self, borders: Tuple[int, int] = (10, 10), color: str = "white"):
        """Add borders to every image.

        :param borders:
        :type borders: Tuple[int, int]
        """
        self._color = color

        width = self._images[0].size[1]  # Use width as a reference

        self._border_x = int(width * (borders[1] / 100))
        self._border_y = int(width * (borders[0] / 100))

        logger.debug("Borders: %s", (self._border_x, self._border_y))

        imgs_len = len(self._images)
        new_imgs = []

        for index in range(imgs_len):
            image = self._images[index]

            bottom = 0 if index != (imgs_len - 1) else self._border_y
            right = 0 if self.lateral and index not in (1, 3, 5) else self._border_x

            box = (self._border_x, self._border_y, right, bottom)

            logger.debug("Applying border: %s", box)
            new_imgs.append(ImageOps.expand(image, border=box, fill=self._color))

        self._images = new_imgs

    def get(self) -> Image.Image:
        """Create the collage."""
        width, height = self._images[0].size

        row, col = self._dimensions
        logger.debug("rXc: %s", (row, col))

        collage_width = row * width
        collage_height = col * height
        new_image = Image.new("RGB", (collage_width, collage_height))
        cursor = (0, 0)

        for image in self._images:
            new_image.paste(image, cursor)
            y = cursor[1]
            x = cursor[0] + width
            if cursor[0] >= (collage_width - width):
                y = cursor[1] + height
                x = 0
            cursor = (x, y)

        logger.debug("Dimmensions: %s", new_image.size)

        if self._border_x is not None:
            return self._fix_bordered(new_image)

        return new_image

    def _fix_bordered(self, image: Image.Image):
        box = (0, 0, self._border_x if self.lateral else 0, self._border_y)
        return ImageOps.expand(image, border=box, fill=self._color)


def _zoom_img(img: Image.Image, zoom_factor=1.3):
    width, height = img.size

    new_width = int(width * zoom_factor)
    new_height = int(height * zoom_factor)

    resized_img = img.resize((new_width, new_height))

    x = int((new_width - width) / 2)
    y = int((new_height - height) / 2)

    cropped_img = resized_img.crop((x, y, x + width, y + height))
    return cropped_img


def _get_from_image_url(url: str):
    name = f"{uuid.uuid3(uuid.NAMESPACE_URL, url)}.png"
    path = os.path.join(CACHED_FRAMES_DIR, name)

    if not os.path.isfile(path):
        download_image(url, path)

    non_transparent = False

    try:
        image = Image.open(path)
    except UnidentifiedImageError:
        raise exceptions.InvalidRequest(f"Not a valid image: {url}")
    else:
        try:
            _test_transparency_mask(image)
        except ValueError:
            logger.debug("Non transparent image found: %s", url)
            non_transparent = True

    image = image.crop(image.getbbox())
    image.thumbnail((1280, 720))
    return image, non_transparent


def _test_transparency_mask(image):
    """
    :raises ValueError
    """
    white = Image.new(size=(100, 100), mode="RGB")
    white.paste(image, (0, 0), image)


def _get_white_level(image):
    grayscale_image = image.convert("L")

    pixel_data = list(grayscale_image.getdata())
    average_intensity = sum(pixel_data) / len(pixel_data)

    whiteness_level = (average_intensity / 255) * 100

    return whiteness_level


def _draw_pixel_grid(image, grid_color=None):
    draw = ImageDraw.Draw(image)

    grid_color = grid_color or "white"  # (255, 0, 0)
    grid_thickness = 1
    font_size = 30
    font = ImageFont.truetype(_DEFAULT_FONT, font_size)

    width, height = image.size

    x_interval = width // 15
    y_interval = height // 15

    for x in range(0, width, x_interval):
        draw.line([(x, 0), (x, height)], fill=grid_color, width=grid_thickness)
        draw.text((x + 2, 2), str(x), fill=grid_color, font=font)

    for y in range(0, height, y_interval):
        draw.line([(0, y), (width, y)], fill=grid_color, width=grid_thickness)
        draw.text((2, y + 2), str(y), fill=grid_color, font=font)

    return image


def _get_used_profiles(value):
    used = [prof for prof in value if prof.get("used") and prof.get("requirements")]
    return "; ".join(str(i.get("name", "n/a")) for i in used)


def _get_info_str(width, height, item: dict):
    image_info = (
        f"Image Size: {width}x{height}\nAspect quotient: {round(width / height, 3)}"
    )

    lines = []
    for key, val in item.items():
        if key == "profiles" and val:
            lines.append(f"Used profiles: {_get_used_profiles(val)}")
            continue

        if not isinstance(val, (str, float, int, bool, tuple)):
            continue

        lines.append(f"{key.replace('_', ' ').capitalize()}: {val}")

    lines = "\n".join(lines)
    return f"{image_info}\n------------------\nCustom post-processing applied:\n{lines}"


def _draw_image_info(image, info=None):
    original_image = image
    width, height = original_image.size
    white_base = Image.new("RGB", (width, height), color="white")

    draw = ImageDraw.Draw(white_base)

    font_size = 25
    font = ImageFont.truetype(_DEFAULT_FONT, size=font_size)

    image_info = _get_info_str(width, height, info or {})

    _, text_height = draw.textsize(image_info, font=font)

    extra_height = text_height + 20
    white_base = white_base.resize((width, height + extra_height))

    white_base.paste(original_image, (0, 0))

    draw = ImageDraw.Draw(white_base)

    draw.text((10, height + 10), image_info, fill="black", font=font)

    return white_base


def _get_debug(image, info=None, grid_color=None):
    _draw_pixel_grid(image, grid_color=grid_color)
    return _draw_image_info(image, info)
