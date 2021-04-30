#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import datetime
import logging
import os
import re
import subprocess
import textwrap
from functools import cached_property
from tempfile import gettempdir
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np
from cv2 import cv2
from pathvalidate import sanitize_filename
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageStat
from pydantic import BaseModel, ValidationError, validator
from srt import Subtitle

import kinobot.exceptions as exceptions

from .badge import Requester, StaticBadge
from .bracket import Bracket
from .constants import CACHED_FRAMES_DIR, FONTS_DIR, FRAMES_DIR
from .item import RequestItem
from .media import Episode, Movie, Song
from .palette import LegacyPalette, Palette
from .story import Story
from .utils import get_dar

_UPPER_SPLIT = re.compile(r"(\s*[.!?♪\-]\s*)")
_STRANGE_RE = re.compile(r"[^a-zA-ZÀ-ú0-9?!\.\ \?',-_*(\n)]")
_BAD_DOTS = re.compile(r"(?u)\.{2,}")

_REPLACEMENTS = (
    (r"<.*?>", ""),
    (_STRANGE_RE, ""),
    (_BAD_DOTS, "..."),
    (" +", " "),
)

_POSSIBLES = {
    1: (1, 1),
    2: (1, 2),
    3: (1, 3),
    4: (1, 4),
}

_VALID_COLLAGES = [(1, 2), (1, 3), (2, 2), (1, 4), (2, 3), (2, 4)]

_FONTS_DICT = {
    "nfsans": os.path.join(FONTS_DIR, "NS_Medium.otf"),
    "helvetica": os.path.join(FONTS_DIR, "helvetica.ttf"),
    "helveticaneue": os.path.join(FONTS_DIR, "helveticaneue.ttf"),
    "clearsans": os.path.join(FONTS_DIR, "ClearSans-Medium.ttf"),
    "comicsans": os.path.join(FONTS_DIR, "comic_sans_ms.ttf"),
    "impact": os.path.join(FONTS_DIR, "impact.ttf"),
    "segoe": os.path.join(FONTS_DIR, "Segoe_UI.ttf"),
    "segoesm": os.path.join(FONTS_DIR, "segoe_semi_bold.ttf"),
    "papyrus": os.path.join(FONTS_DIR, "papyrus.ttf"),
    "bangers": os.path.join(FONTS_DIR, "Bangers-Regular.ttf"),
    "timesnewroman": os.path.join(FONTS_DIR, "TimesNewRoman.ttf"),
    "oldenglish": os.path.join(FONTS_DIR, "OldEnglish.ttf"),
}

_DEFAULT_FONT = os.path.join(FONTS_DIR, "segoe_semi_bold.ttf")


logger = logging.getLogger(__name__)


class Frame:
    """Class for single frames with intended post-processing."""

    def __init__(self, media: Union[Movie, Episode], bracket: Bracket):
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

        self.cv2: np.ndarray
        self.pil: Image.Image

    def load_frame(self):
        " Load the cv2 array and the PIL image object. "
        if self._is_cached():
            self._load_pil_from_cv2()
        else:
            if self.media.type == "song":
                self._extract_frame_youtube_dl()
            else:
                self._extract_frame_cv2()
                self._fix_dar()

            self._load_pil_from_cv2()

            self._cache_image()

    def load_palette(self, classic: bool = True):
        assert self.pil is not None

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
        assert self.media.path is not None

        path = self.media.path
        if self.media.type != "song":
            path = os.path.basename(path)

        if self.message is not None:
            path = path + self.message[:3]

        path = sanitize_filename(path)

        return f"{path}_{self.seconds}_{self.milliseconds}.jpg"

    def _cache_image(self):
        image_path = os.path.join(CACHED_FRAMES_DIR, self.discriminator)
        logger.info("Caching image: %s", image_path)

        self.pil.save(image_path)

    def _is_cached(self) -> bool:
        image_path = os.path.join(CACHED_FRAMES_DIR, self.discriminator)
        if os.path.isfile(image_path):
            logger.info("Nothing to do. Cached image found: %s", self.discriminator)
            self.cv2 = cv2.imread(image_path)
            return True

        return False

    def _extract_frame_cv2(self):  # path, second, milliseconds):
        """
        Get an image array based on seconds and milliseconds with cv2.
        """
        assert self.media.capture is not None

        extra_frames = int(self.media.fps * (self.milliseconds * 0.001))

        frame_start = int(self.media.fps * self.seconds) + extra_frames

        logger.debug("Frame to extract: %s from %s", frame_start, self.media.path)

        self.media.capture.set(1, frame_start)
        frame = self.media.capture.read()[1]

        if frame is None:
            raise exceptions.InexistentTimestamp(
                f"This timestamp doesn't exist: {self.seconds}ss"
            )
        self.cv2 = frame

    def _extract_frame_youtube_dl(self):
        timestamp = f"{self.seconds}.{self.milliseconds}"
        logger.info("Extracting %s from %s", timestamp, self.media.path)

        path = os.path.join(gettempdir(), f"{self.media.id}.png")

        command = f"video_frame_extractor {self.media.path} {timestamp} {path}"

        try:
            subprocess.call(command, stdout=subprocess.PIPE, shell=True, timeout=10)
        except subprocess.TimeoutExpired as error:  # To use base exceptions later
            raise exceptions.KinoUnwantedException(
                f"Unexpected error extracting frame: {type(error).__name__}"
            ) from None

        if os.path.isfile(path):
            logger.info("Extraction OK")
            self.cv2 = cv2.imread(path)
            if self.cv2 is None:
                raise exceptions.InexistentTimestamp(
                    f"This timestamp doesn't exist: {self.seconds}ss"
                )
        else:
            raise exceptions.InexistentTimestamp(
                f"External error extracting second '{timestamp}' from video"
            )

    def _load_pil_from_cv2(self):
        self.pil = _load_pil_from_cv2(self.cv2)

    def _cv2_trim(self) -> bool:
        """
        Remove black borders from a cv2 image array.

        :param cv2_image: cv2 image array
        """
        logger.info("Trying to remove black borders with cv2")
        og_w, og_h = self.cv2.shape[1], self.cv2.shape[0]
        logger.debug("Original dimensions: %dx%d", og_w, og_h)
        og_quotient = og_w / og_h

        first_img = _remove_lateral_cv2(self.cv2)

        tmp_img = cv2.transpose(first_img)
        tmp_img = cv2.flip(tmp_img, flipCode=1)

        if tmp_img is None:
            raise exceptions.InvalidRequest("Possible all-black image found")

        final = _remove_lateral_cv2(tmp_img)

        out = cv2.transpose(final)

        final_img = cv2.flip(out, flipCode=0)

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

        self.cv2 = final_img
        return True

    def _fix_dar(self):
        return _fix_dar(self.cv2, get_dar(self.media.path))

    def __repr__(self):
        return f"<Frame: {self.media.title} - {self.pretty_content}>"


class GIF:
    """Class for GIF requests with minimal post-processing."""

    def __init__(
        self,
        media: Union[Movie, Episode],
        content_list,
        id: str,
    ):
        self.media = media
        self.id = id
        self.brackets = content_list
        self.pils: List[Image.Image] = []
        self.subtitles: List[Subtitle] = []
        self.range_: Union[None, Tuple] = None

        self._sanity_checks()

        if not self._is_range_request():
            self.subtitles = self.brackets
        else:
            self.range_ = tuple(tstamp for tstamp in self.brackets[0].content)

    @property
    def title(self) -> str:
        return self.media.pretty_title

    @classmethod
    def from_request(cls, request):
        """Load an item from a Request class.

        :param request:
        :type request: Request
        """
        assert request.type == "!gif"
        items = request.items

        if any(mreq.media.type == "song" for mreq in items):
            raise exceptions.InvalidRequest("Songs don't support GIF requests")

        if len(items) > 1:
            raise exceptions.InvalidRequest("GIF requests don't support multiple items")

        item = items[0]
        item.compute_brackets()
        return cls(item.media, item.brackets, request.id)

    def get(self, path: Optional[str] = None) -> List[str]:  # Consistency
        self.media.load_capture_and_fps()

        path = path or os.path.join(CACHED_FRAMES_DIR, self.id)
        os.makedirs(path, exist_ok=True)

        gif_path = os.path.join(path, f"{self.id}.gif")

        logger.debug("GIF path to save: %s", gif_path)

        if self.subtitles is not None:
            self.pils = list(self._get_image_list_from_subtitles())
        elif self.range_ is not None:
            self.pils = list(self._get_image_list_from_range())

        self._image_list_to_gif(gif_path)

        return [gif_path]

    def _is_range_request(self):
        return len(self.brackets) == 1 and isinstance(self.brackets[0].content, tuple)

    def _sanity_checks(self):
        if self.media.type == "song":
            raise exceptions.InvalidRequest("Songs doesn't support GIF requests")

        if len(self.brackets) > 4:
            raise exceptions.InvalidRequest(
                f"Expected less than 5 quotes, found {len(self.brackets[0])}."
            )

        if len(self.brackets) > 1 and isinstance(self.brackets[0], tuple):
            raise exceptions.InvalidRequest(
                "No more than one range brackets are allowed"
            )

    def _start_end_gif_quote(self, subtitle: Subtitle):
        logger.debug(self.media.fps)
        extra_frames_start = int(
            self.media.fps * (subtitle.start.microseconds * 0.000001)
        )
        extra_frames_end = int(self.media.fps * (subtitle.end.microseconds * 0.000001))
        frame_start = int(self.media.fps * subtitle.start.seconds) + extra_frames_start
        frame_end = int(self.media.fps * subtitle.end.seconds) + extra_frames_end
        return frame_start, frame_end

    def _start_end_gif_timestamp(self):
        assert isinstance(self.range_, tuple)
        logger.debug("FPS: %s X %s", self.media.fps, self.range_)

        return (
            int(self.media.fps * self.range_[0]),
            int(self.media.fps * self.range_[1]),
        )

    def _get_image_list_from_range(self):
        assert self.media.capture is not None and self.media.path is not None
        basename_ = os.path.basename(self.media.path)
        logger.info("About to extract GIF for range %s", self.range_)

        dar = get_dar(self.media.path)

        start, end = self._start_end_gif_timestamp()

        logger.info("Start: %d - end: %d", start, end)
        for i in range(start, end, 4):
            path = os.path.join(CACHED_FRAMES_DIR, f"{basename_}_{start}_gif.jpg")
            if os.path.isfile(path):
                logger.debug("Cached image found")
                yield Image.open(path)
            else:
                self.media.capture.set(1, i)

                frame_ = self.media.capture.read()[1]
                frame_ = _load_pil_from_cv2(_scale_to_gif(_fix_dar(frame_, dar)))
                frame_.save(path)
                yield frame_

    def _get_image_list_from_subtitles(self):
        """
        :param path: video path
        :param subs: list of subtitle dictionaries
        :param dar: display aspect ratio from video
        """
        assert self.media.capture is not None and self.media.path is not None
        basename_ = os.path.basename(self.media.path)

        dar = get_dar(self.media.path)

        for subtitle in self.subtitles:
            start, end = self._start_end_gif_quote(subtitle)
            end += 10
            end = end if abs(start - end) < 100 else (start + 100)
            logger.info("Start: %d - end: %d", start, end)
            for i in range(start, end, 4):
                path = os.path.join(CACHED_FRAMES_DIR, f"{basename_}_{start}_gif.jpg")
                if os.path.isfile(path):
                    logger.debug("Cached image found")
                    image = Image.open(path)
                else:
                    self.media.capture.set(1, i)
                    frame_ = self.media.capture.read()[1]
                    image = _load_pil_from_cv2(_scale_to_gif(_fix_dar(frame_, dar)))
                    image.save(path)

                _draw_quote(image, subtitle.content, False)
                yield image

    def _image_list_to_gif(self, path: str):
        """
        :param images: list of PIL.Image objects
        :param filename: output filename
        """
        assert len(self.pils) > 0

        logger.info("Saving GIF: %d PIL images", len(self.pils))

        self.pils[0].save(
            path, format="GIF", append_images=self.pils[1:], save_all=True
        )

        for pil in self.pils:
            pil.close()

        logger.info("Saved: %s", path)


_ASPECT_THRESHOLD = {1: 1.65, 2: 1.8, 3: 2.2, 4: 2.3}


class PostProc(BaseModel):
    """
    Class for post-processing options applied in an entire request.

    Usage in request strings
    =======================

    The following post-processing options modify the entire request. All of
    these are intended for advanced usage. Detected abuse may lead an user to
    get blocked; gratuitous usage (e.g. calling defaults) may lead at people
    laughing at your clownery.

    Syntax:
            `!REQ_TYPE ITEM [BRACKET]... [--flag]`

    An example of functional usage of request post-processing would look like
    this:

            `!req Taxi Driver [40:40] [45:00] --contrast 10 --aspect-quotient 1.1`

    Optional arguments:

    - `--raw`: don't crop the images (default: False)

    - `--ultraraw`: like `--raw`, but don't draw quotes (default: False)

    - `--font` FONT:

        A custom font to use for every image (default: `segoesm`).

        Available font values:
            `segoesm`
            `segoe`
            `helveticaneue`
            `helvetica`
            `clearsans`
            `nfsans`
            `comicsans`
            `papyrus`
            `impact`
            `bangers`
            `timesnewroman`
            `oldenglish`

        .. warning::
            Ensure that your joke is **really** funny when you request Comic
            Sans, Papyrus or Impact.
        .. note::
            Kinobot will default to `segoesm` if you type a non-existent font
            value.

    .. note::
        Most of the following descriptions were partially taken from the
        Pillow (PIL Fork) documentation.

    - `--font-size` FLOAT | INT: a relative (to the image) font size
    (default: 27.5)

    - `--font-color` COLOR: a color string; it can be a common html name
    (e.g. black, white, etc.) or a hexadecimal value (default: white)

    - `--text-spacing` FLOAT: the number of pixels between lines (default: 1)

    - `--text-align` STR: the relative alignment of lines; it can be left,
    center or right (default: center)

    - `--y-offset` INT: the relative vertical offset of the text (default: 85)

    - `--stroke-width` INT: the relative stroke width (font border size for
    technologically illiterate cinephiles) (default: 3)

    - `--stroke-color` COLOR: same as `--font-color`, but for the stroke
    (default: black)


    - `--aspect-quotient` FLOAT:

        The aspect ratio's quotient that will be applied for every image.
        By default, Kinobot will detect the "ideal" aspect ratio by amount
        of images (e.g. 1.6 for one image; 1.8 for two images).

        .. warning::
            This flag will raise `InvalidRequest` if the quotient is greater
            than 2.4 or lesser than 1.1.

    - `--brightness` INT: -100 to 100 brightness to apply to all the images (default: 0)
    - `--color` INT: -100 to 100 color to apply to all the images (default: 0)
    - `--contrast` INT: -100 to 100 contrast to apply to all the images (default: 30)
    - `--sharpness` INT: -100 to 100 sharpness to apply to all the images (default: 0)

    - `--no-collage`: don't try to draw a collage, no matter the amount of
    frames (default: False)

        .. warning::
            `--no-collage` is **highly discouraged** as it is spammy; you might
            piss off people in the server with your experimental dumbassery.
            Use it only when you know what you are doing.

    - `--dimensions`:

        The dimensions of the collage that Kinobot should draw. By default,
        Kinobot will detect this automatically. You can choose between 1x2,
        1x3, 2x2, 1x4, 2x3 and 2x4.

        .. note::
            These values should match the amount of frames produced (e.g 2x2
            for 4 frames, 1x2 for 2 frames, etc).
    """

    frame: Union[Frame, None] = None
    font = "segoesm"
    font_size: float = 27.5
    font_color = "white"
    text_spacing: float = 1.0
    text_align = "center"
    y_offset = 85
    stroke_width = 3
    stroke_color = "black"
    raw = False
    ultraraw = False
    no_collage = False
    dimensions: Union[None, str, tuple] = None
    aspect_quotient = 1.65
    contrast = 20
    color = 0
    brightness = 0
    sharpness = 0

    class Config:
        arbitrary_types_allowed = True

    def process(self, frame: Frame, draw: bool = True) -> Image.Image:
        """Process a frame and return a PIL Image object.

        :param frame:
        :type frame: Frame
        :param draw:
        :type draw: bool
        :rtype: Image.Image
        """
        logger.debug("Processing frame: %s", frame)
        self.frame = frame

        self.raw = self.ultraraw or self.raw

        if not self.raw:
            self._crop()
            self._pil_enhanced()

        if draw and not self.ultraraw:
            self._draw_quote()

        return self.frame.pil

    def process_list(self, frames: List[Frame] = None) -> List[Image.Image]:
        """Handle a list of frames, taking into account the post-processing
        flags.

        :param frames:
        :type frames: List[Frame]
        :rtype: List[Image.Image]
        """
        frames = frames or []

        logger.debug("Requested dimensions: %s", self.dimensions)

        if (
            self.dimensions is not None
            and len(frames) != (self.dimensions[0] * self.dimensions[1])  # type: ignore
            and self.no_collage is False
        ):
            raise exceptions.InvalidRequest(
                f"Kinobot returned {len(frames)} frames; such amount is compatible"
                f" with the requested collage dimensions: {self.dimensions}"
            )

        if self.dimensions is None:
            self.dimensions = _POSSIBLES.get(len(frames))  # Still can be None

        logger.debug("Found dimensions: %s", self.dimensions)

        pils = [self.process(frame, draw=False) for frame in frames]
        pils = _homogenize_images(pils)

        assert len(pils) == len(frames)

        if not self.ultraraw:  # Don't even bother
            for pil, frame in zip(pils, frames):
                if frame.message is not None:
                    _draw_quote(pil, frame.message, **self.dict())

        if self.no_collage or (self.dimensions is None and len(frames) > 4):
            return pils

        return [_get_collage(pils, self.dimensions)]  # type: ignore

    def _pil_enhanced(self):
        if self.contrast:
            logger.debug("Applying contrast: %s", self.contrast)
            contrast = ImageEnhance.Contrast(self.frame.pil)
            self.frame.pil = contrast.enhance(1 + self.contrast * 0.01)
        if self.brightness:
            logger.debug("Applying brightness: %s", self.brightness)
            brightness = ImageEnhance.Brightness(self.frame.pil)
            self.frame.pil = brightness.enhance(1 + self.brightness * 0.01)
        if self.sharpness:
            logger.debug("Applying sharpness: %s", self.sharpness)
            sharpness = ImageEnhance.Sharpness(self.frame.pil)
            self.frame.pil = sharpness.enhance(1 + self.sharpness * 0.01)
        if self.color:
            logger.debug("Applying color: %s", self.color)
            sharpness = ImageEnhance.Color(self.frame.pil)
            self.frame.pil = sharpness.enhance(1 + self.color * 0.01)

    def _draw_quote(self):
        if self.frame.message is not None:
            try:
                _draw_quote(self.frame.pil, self.frame.message, **self.dict())
            except ValueError as error:
                raise exceptions.InvalidRequest(error) from None

    def _crop(self):
        x_off = self.frame.bracket.postproc.x_crop_offset
        y_off = self.frame.bracket.postproc.y_crop_offset
        self.frame.pil = _crop_by_threshold(
            self.frame.pil, self.aspect_quotient, x_off=x_off, y_off=y_off
        )

    @validator("stroke_width", "text_spacing")
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

    @validator("contrast", "brightness", "color", "sharpness", "font_size")
    @classmethod
    def _check_100(cls, val):
        if abs(val) > 100:
            raise exceptions.InvalidRequest("Values greater than 100 are not allowed")

        return val

    @validator("aspect_quotient")
    @classmethod
    def _check_ap(cls, val):
        if 1 > val < 2.5:
            raise exceptions.InvalidRequest(f"Expected 1>|<2.5, found {val}")

        return val

    @validator("font")
    @classmethod
    def _check_font(cls, val):
        if val not in _FONTS_DICT:
            return "segoesm"

        return val

    @validator("dimensions")
    @classmethod
    def _check_dimensions(cls, val):
        if val is None:
            return None

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


class Static:
    """Class for static requests with advanced post-processing."""

    def __init__(self, items: Sequence[RequestItem], type_: str, id_: str, **kwargs):
        self.items = items
        self.id: str = id_
        self.type: str = type_

        self.frames: List[Frame] = []

        self._paths = []

        try:
            self._postproc = PostProc(**kwargs)
        except ValidationError as error:
            raise exceptions.InvalidRequest(error) from None

        self._raw: Union[Image.Image, None] = None

    @classmethod
    def from_request(cls, request):
        return cls(request.items, request.type, request.id, **request.args)

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

        single_img = os.path.join(path, "00.jpg")
        self._paths.append(single_img)

        if len(self.frames) == 1:
            logger.debug("Single static image found: %s", single_img)

            frame = self.frames[0]
            self._postproc.process(frame).save(single_img)

        else:
            images = self._postproc.process_list(self.frames)

            if len(images) == 1:
                images[0].save(single_img)
            else:
                self._paths.pop(0)
                for num, image in enumerate(images):
                    path_ = os.path.join(path, f"{num:02}.jpg")
                    logger.debug("Saving image: %s", path_)
                    image.save(path_)
                    self._paths.append(path_)

        logger.debug("Final paths: %s", self._paths)

        return self._paths

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

    @cached_property
    def badges(self) -> List[StaticBadge]:
        """Return a list of valid badges for the movies inside a request.

        :rtype: List[StaticBadge]
        """
        badges = []

        # Temporary: automatically append a requester badge for episodes
        badges.append(Requester())

        media_items = [
            item.media for item in self.items if isinstance(item.media, Movie)
        ]

        for badge in StaticBadge.__subclasses__():
            for media in media_items:
                bdg = badge()
                if any(isinstance(bdg, type(seen)) for seen in badges):  # Avoid dupes
                    logger.debug("Duplicate badge: %s", badge)
                    continue

                if bdg.check(media):
                    badges.append(bdg)

        logger.debug("Returned badges: %s", badges)
        return badges

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
        logger.debug("Type: %s", self.type)
        if self.type == "!parallel":
            header = self._get_parallel_header()
            if " | " in header:  # Ensure that the request is a parallel
                return "\n".join((header, "Category: Kinema Parallels"))

        header = self.initial_item.media.simple_title
        sub = ""

        if self.initial_item.media.type != "song":
            sub = self.initial_item.media.metadata.request_title  # type: ignore

        return "\n".join((header, sub))

    @property
    def images(self) -> List[str]:  # Consistency
        " List of generated image paths. "
        return self._paths

    def _load_frames(self):
        for request in self.items:
            request.compute_brackets()

            if not isinstance(request.media, Song):
                request.media.load_capture_and_fps()

            for frame in request.brackets:  # Change name later
                frame_ = Frame(request.media, frame)  # type: ignore
                frame_.load_frame()

                logger.debug("Appending frame: %s", frame_)

                self.frames.append(frame_)

        # For stories
        self._raw = self.frames[0].pil

        frames_len = len(self.frames)
        logger.debug("Loaded frames: %s", frames_len)

        limit = 5 if self.type == "!parallel" else 4
        new_aq = _ASPECT_THRESHOLD[frames_len if frames_len < limit else 1]

        logger.debug("Aspect quotient set: %s", self._postproc.aspect_quotient)
        logger.debug("Guessed aspect quotient: %s", new_aq)

        if self._postproc.aspect_quotient == 1.65:  # default
            self._postproc.aspect_quotient = new_aq

        if self.type == "!palette":
            logger.debug("Loading palette")
            self.frames[0].load_palette(False)
            self._postproc.raw, self._postproc.ultraraw = True, True

        logger.debug("Final aspect quotient set: %s", self._postproc.aspect_quotient)

        assert len(self.frames) > 0

    def _get_parallel_header(self) -> str:
        titles = [item.media.simple_title for item in self.items]
        # Remove dupes
        return " | ".join(list(dict.fromkeys(titles)))

    def __repr__(self) -> str:
        return f"<Static ({len(self.items)} items)>"


def _crop_by_threshold(
    image: Image.Image, threshold: float = 1.65, **kwargs
) -> Image.Image:
    logger.debug("Passed kwargs: %s", kwargs)
    width, height = image.size
    init_w, init_h = width, height
    quotient = width / height
    inc = 0
    limit = 150

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
                    crop_tuple[1] + offset,
                    crop_tuple[3],
                )

            crop_tuple = tuple(crop_tuple)
            logger.info("Final quotient and crop tuple: %s - %s", quotient, crop_tuple)
            return image.crop(crop_tuple)

        if inc > limit:
            raise NotImplementedError(
                f"An infinite loop was prevented: {init_w}/{init_w}"
            )


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
    """Draw a quote into a PIL Image object.

    :param image:
    :type image: Image.Image
    :param quote:
    :type quote: str
    :param modify_text:
    :type modify_text: bool
    :param kwargs:
        * font
        * font_size
        * font_color
        * text_spacing
        * text_align
        * y_offset
        * stroke_width
        * stroke_color
    """
    font = _FONTS_DICT.get(kwargs.get("font", "")) or _DEFAULT_FONT
    draw = ImageDraw.Draw(image)

    if modify_text:
        quote = _prettify_quote(_clean_sub(quote))

    logger.info("About to draw quote: %s (font: %s)", quote, font)

    width, height = image.size

    scale = kwargs.get("font_size", 27.5) * 0.001

    font_size = int((width * scale) + (height * scale))
    font = ImageFont.truetype(font, font_size)

    off = int(width * (kwargs.get("y_offset", 85) * 0.001))

    txt_w, txt_h = draw.textsize(quote, font)

    draw_h = height - txt_h - off

    draw.text(
        ((width - txt_w) / 2, draw_h),
        quote,
        kwargs.get("font_color", "white"),
        font=font,
        align=kwargs.get("text_align", "center"),
        spacing=kwargs.get("text_spacing", 0.8),
        stroke_width=int(width * (kwargs.get("stroke_width", 3) * 0.001)),
        stroke_fill=kwargs.get("stroke_color", "black"),
    )


def _load_pil_from_cv2(cv2_img: np.ndarray):
    """
    Convert an array to a PIL.Image object.
    """
    # assert isinstance(self.cv2, cv2)
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


def _prettify_quote(text: str) -> str:
    """
    Adjust line breaks to correctly draw a subtitle.

    :param text: text
    """
    lines = [" ".join(line.split()) for line in text.split("\n")]
    final_text = "\n".join(lines)

    if len(lines) == 2 and not any("-" in line for line in lines):
        if abs(len(lines[0]) - len(lines[1])) > 30:
            final_text = _harmonic_wrap(final_text.replace("\n", " "))

    if (len(lines) == 1 and len(text) > 35) or len(lines) > 2:
        final_text = _harmonic_wrap(final_text)

    if len(re.findall("-", final_text)) == 1 and final_text.startswith("-"):
        final_text = final_text.replace("-", "").strip()

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


def _remove_lateral_cv2(cv2_image):
    """
    :param cv2_image: cv2 image array
    """
    width = cv2_image.shape[1]

    for i in range(width):
        if np.mean(cv2_image[:, i, :]) > 1.7:
            break

    for j in range(width - 1, 0, -1):
        if np.mean(cv2_image[:, j, :]) > 1.7:
            break

    return cv2_image[:, i : j + 1, :].copy()  # type: ignore


def _clean_sub(text: str) -> str:
    """
    Remove unwanted characters from a subtitle string.

    :param text: text
    """
    logger.debug("About to clean subtitle: %s", text)
    if text.isupper():
        logger.debug("Fixing all uppercase string: %s", text)
        text = "".join([s.capitalize() for s in _UPPER_SPLIT.split(text)])

    for replacement in _REPLACEMENTS:
        # logger.debug("Using %s replacement. Og text: %s", replacement[0], text)
        text = re.sub(replacement[0], replacement[1], text)
        # logger.debug("Result: %s", text)

    logger.debug("Result: %s", text)
    return text.strip()


def _get_collage(
    images: List[Image.Image], dimensions: Optional[Tuple[int, int]] = None
) -> Image.Image:
    """Create a collage from a list of PIL Image objects.

    :param images:
    :type images: List[Image.Image]
    :param dimensions:
    :type dimensions: Optional[tuple]
    :rtype: Image.Image
    """
    width, height = images[0].size

    row, col = dimensions or _POSSIBLES[len(images)]
    logger.debug("rXc: %s", (row, col))

    collage_width = row * width
    collage_height = col * height
    new_image = Image.new("RGB", (collage_width, collage_height))
    cursor = (0, 0)

    for image in images:
        new_image.paste(image, cursor)
        y = cursor[1]
        x = cursor[0] + width
        if cursor[0] >= (collage_width - width):
            y = cursor[1] + height
            x = 0
        cursor = (x, y)

    return new_image
