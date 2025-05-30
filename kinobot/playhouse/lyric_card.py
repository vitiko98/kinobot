from dataclasses import dataclass
import datetime
import functools
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import re
import tempfile
import time
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from fuzzywuzzy import process as fuzz_process
from lyricsgenius import Genius  # type: ignore
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import validator
import requests
import requests_cache

from kinobot.playhouse.utils import get_colors

logger = logging.getLogger(__name__)


class ProxyManager:
    def __init__(
        self,
        token: str,
        proxy_file: str = "proxies.txt",
        max_retries: int = 5,
        backoff_base: float = 1.0,
    ):
        self._token = token
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._proxies = self._load_proxies(Path(proxy_file))
        self._blacklist = set()
        self._last_good_proxy = None

    def get_working_genius(self, fn):
        attempts = 0
        last_error = None
        tried = set()

        def try_proxy(proxy):
            nonlocal last_error
            key = self._proxy_repr(proxy)
            if key in tried or key in self._blacklist:
                return None
            tried.add(key)

            try:
                genius = Genius(self._token, proxies=proxy or {})
                result = fn(genius)
                self._last_good_proxy = proxy
                return result
            except requests.exceptions.Timeout:
                logger.info("Timeout with proxy, retrying...")
                self._blacklist_proxy(proxy)
                self._backoff(attempts)
                last_error = requests.exceptions.Timeout()
            except Exception as exc:
                logger.warning(f"Error with proxy: {exc}")
                self._blacklist_proxy(proxy)
                last_error = exc
            return None

        if self._last_good_proxy:
            if attempts >= self._max_retries:
                raise last_error or RuntimeError("Max retries reached")

            result = try_proxy(self._last_good_proxy)
            attempts += 1
            if result:
                return result

        for proxy in self._proxies:
            if attempts >= self._max_retries:
                break
            result = try_proxy(proxy)
            attempts += 1
            if result:
                return result

        raise last_error or RuntimeError("All proxy attempts failed")

    def _load_proxies(self, file_path: Path):
        if not file_path.exists():
            return [None]

        with file_path.open(encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        random.shuffle(lines)

        proxies = []
        for line in lines:
            ip, port, user, pwd = line.split(":")
            proxies.append(
                {
                    "http": f"http://{user}:{pwd}@{ip}:{port}",
                    "https": f"http://{user}:{pwd}@{ip}:{port}",
                }
            )

        proxies.append(None)  # direct fallback
        return proxies

    def _blacklist_proxy(self, proxy):
        if proxy:
            self._blacklist.add(self._proxy_repr(proxy))

    def _proxy_repr(self, proxy):
        return str(proxy["http"]) if proxy else "direct"

    def _backoff(self, attempt: int):
        return
        # delay = self._backoff_base * (2**attempt)
        # logger.debug(f"Backoff sleeping for {delay:.2f} seconds")
        # time.sleep(delay)


def json_cache(cache_dir=None, expire_seconds=864000, *, load_fn=None, dump_fn=None):
    if cache_dir is None:
        cache_dir = os.path.join(tempfile.gettempdir(), "song_cache")
    os.makedirs(cache_dir, exist_ok=True)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            relevant_args = args[1:] if args and hasattr(args[0], "__class__") else args
            key_data = repr((func.__name__, relevant_args, kwargs)).encode("utf-8")
            key = hashlib.md5(key_data).hexdigest()
            cache_path = os.path.join(cache_dir, f"{key}.json")
            meta_path = os.path.join(cache_dir, f"{key}.meta")

            if os.path.exists(cache_path) and os.path.exists(meta_path):
                try:
                    with open(meta_path, "r") as meta_file:
                        timestamp = float(meta_file.read())
                    if time.time() - timestamp < expire_seconds:
                        with open(cache_path, "r", encoding="utf-8") as f:
                            raw = json.load(f)
                            return load_fn(raw) if load_fn else raw
                    else:
                        os.remove(cache_path)
                        os.remove(meta_path)
                except Exception:
                    pass

            result = func(*args, **kwargs)
            if result is not None:
                logger.debug("Cached song found.")
                data = dump_fn(result) if dump_fn else result
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                with open(meta_path, "w") as meta_file:
                    meta_file.write(str(time.time()))
            return result

        return wrapper

    return decorator


# Design based on https://ehmorris.com/lyriccardgenerator and Genius app


class _WhiteBaseTrace(BaseModel):
    white_base_height: int
    line_thickness: int
    original_height: int
    new_width: int
    new_height: int
    resultant_base_height: int
    y_position: int


def add_white_base_with_separator(
    image, base_height=25, line_thickness=2, base_color="#412C5D", line_color="#EEDFCE"
):
    original_image = image

    width, height = original_image.size

    white_base_height = _get_percentage(base_height, height)
    line_thickness = _get_percentage(line_thickness, white_base_height)

    new_height = height + white_base_height
    new_image = Image.new("RGB", (width, new_height), color=base_color)

    new_image.paste(original_image, (0, 0))

    draw = ImageDraw.Draw(new_image)
    draw.rectangle([(0, height), (width, height + line_thickness)], fill=line_color)  # type: ignore

    return new_image, _WhiteBaseTrace(
        white_base_height=white_base_height,
        line_thickness=line_thickness,
        new_width=width,
        new_height=new_height,
        resultant_base_height=white_base_height - line_thickness,
        y_position=new_height - (white_base_height - line_thickness),
        original_height=height,
    )


def _get_percentage_of(value, total):
    return int((value / total) * 100)


def _get_percentage(percentage, total) -> int:
    return int((percentage / 100) * total)


def add_text(
    image,
    text,
    base_height,
    y_position,
    font_size=20,
    x_padding=6,
    text_color="white",
    font=None,
):
    width, height = image.size

    draw = ImageDraw.Draw(image)

    font_path = font or "fonts/Programme-Regular.ttf"

    font = None
    font_size = _get_percentage(font_size, base_height)

    for _ in range(100):
        font = ImageFont.truetype(font_path, font_size)
        text_width, text_height = draw.textsize(text, font=font)  # type: ignore

        y = (base_height - text_height) / 2

        x = _get_percentage(x_padding, width)

        text_margin = width - x
        if text_margin > text_width + x:
            return draw.text((x, y_position + y), text, fill=text_color, font=font)

        font_size -= 1

    raise NotImplementedError("Infinite loop prevented")


class _RectangleTextTrace(BaseModel):
    x: int
    y: int
    text_width: int
    text_height: int
    rectangle_width: int
    rectangle_height: int
    original_y: int


def add_text_with_rectangle(
    image,
    text,
    x_y=(68, 400),
    border=40,
    font_scale=6,
    rectangle_color="white",
    text_color="black",
    font=None,
    rectangle_y=None,
    fixed_font_size=None,
):
    width, height = image.size

    draw = ImageDraw.Draw(image)

    font_path = font or "fonts/programme_light.otf"

    font_size = fixed_font_size or _get_percentage(font_scale, height)
    font = ImageFont.truetype(font_path, font_size)

    text_width, text_height = draw.textsize(text, font=font)  # type: ignore

    x, y = x_y

    rectangle_x = x + text_width + _get_percentage(border, text_height)
    rectangle_y = rectangle_y or (text_height + _get_percentage(border, text_height))

    draw.rectangle([x, y, rectangle_x, y + rectangle_y], fill=rectangle_color)  # type: ignore

    text_x = (x + rectangle_x - text_width) / 2

    rectangle_height = rectangle_y
    text_y = y + ((rectangle_height - text_height) / 2)

    draw.text((text_x, text_y), text, fill=text_color, font=font)

    return _RectangleTextTrace(
        x=int(text_x),
        y=int(text_y),
        text_width=text_width,
        text_height=text_height,
        rectangle_width=rectangle_x - x,
        rectangle_height=rectangle_y,
        original_y=y,
    )


def _get_font_size(x_y, text, font_scale, image, border, font=None):
    width, height = image.size
    draw = ImageDraw.Draw(image)

    font_size = _get_percentage(font_scale, height)
    font_path = font or "fonts/programme_light.otf"

    for _ in range(100):
        font = ImageFont.truetype(font_path, font_size)

        text_width, text_height = draw.textsize(text, font=font)  # type: ignore

        x, y = x_y

        rectangle_x = x + text_width + _get_percentage(border, text_height)

        margin = width - x

        rectangle_end = x + rectangle_x

        logger.debug("Margin: %s; rectangle end: %s", margin, rectangle_end)

        if rectangle_end <= margin:
            return font_size

        font_size -= 1

    raise NotImplementedError


def draw_multiline(
    image,
    text,
    x_scale=6,
    y_scale=85,
    separator=1.5,
    border=40,
    font_scale=6,
    rectangle_color="white",
    text_color="black",
    font=None,
):
    width, height = image.size

    x = _get_percentage(x_scale, width)
    y = _get_percentage(y_scale, height)

    args = (border, font_scale, rectangle_color, text_color)

    separator = _get_percentage(separator, height)

    trace = None

    lines = text.split("\n")[::-1]

    font_size = _get_font_size(
        (x, y), max(lines, key=len), font_scale, image, border, font=font
    )
    kwargs = dict(fixed_font_size=font_size, font=font)

    for line in lines:
        if trace is None:
            trace = add_text_with_rectangle(image, line, (x, y), *args, **kwargs)
        else:
            new_y = trace.original_y - trace.rectangle_height - separator
            trace = add_text_with_rectangle(
                image,
                line,
                (x, new_y),
                *args,
                rectangle_y=trace.rectangle_height,
                **kwargs,
            )


def make_card(
    image: Image.Image,
    title: str,
    lyrics: str,
    title_color_factory=None,
    title_x=6,
    title_font_size=20,
    title_font=None,
    title_height=25,
    lyrics_x=6,
    lyrics_y=85,
    lyrics_separator=1.5,
    lyrics_font_border=40,
    lyrics_font_size=6,
    lyrics_font=None,
    lyrics_color_factory=lambda image: ("white", "black"),
):
    colors = (title_color_factory or get_colors)(image)
    bg, fg = colors[0], colors[-1]

    l_colors = lyrics_color_factory(image)
    l_bg, l_fg = l_colors[0], l_colors[-1]

    draw_multiline(
        image,
        lyrics,
        x_scale=lyrics_x,
        y_scale=lyrics_y,
        separator=lyrics_separator,
        border=lyrics_font_border,
        font_scale=lyrics_font_size,
        rectangle_color=l_bg,
        text_color=l_fg,
        font=lyrics_font,
    )
    image_, trace = add_white_base_with_separator(
        image, base_color=bg, line_color=fg, base_height=title_height
    )
    add_text(
        image_,
        title,
        trace.resultant_base_height,
        trace.y_position,
        text_color=fg,
        font_size=title_font_size,
        x_padding=title_x,
        font=title_font,
    )
    return image_


_GENIUS_URL = "https://genius.com"


class Genius(Genius):
    def __init__(self, *args, **kwargs):
        n_kwargs = {k: v for k, v in kwargs.items() if k != "proxies"}

        super().__init__(*args, **n_kwargs)

        previous_headers = self._session.headers

        self._proxies = kwargs.get("proxies", {})
        logger.debug(self._proxies)
        self._session = requests.Session()
        self._session.headers = previous_headers
        logger.debug(self._session.headers)

    def _____init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        previous_headers = self._session.headers
        cache_path = os.path.join(tempfile.gettempdir(), __name__ + ".cache")

        self._session = requests_cache.CachedSession(
            cache_path, expire_after=datetime.timedelta(hours=1)
        )
        self._session.headers = previous_headers

    def _make_request(self, *args, **kwargs):
        logger.debug("Making modified request")
        return super()._make_request(*args, **kwargs, proxies=self._proxies)

    def get_id_from_url(self, url):
        url = url.replace(_GENIUS_URL + "/", "")

        text = self._make_request(url, web=True)
        soup = BeautifulSoup(text, "lxml")  # type: ignore

        try:
            meta = soup.find("meta", {"property": "twitter:app:url:iphone"})["content"]  # type: ignore
            return meta.split("/")[-1]  # type: ignore
        except Exception as error:
            logger.info("Error getting ID: %s", error)
            return None


def get_lyrics_line(query: str, lyrics: str):
    query = query.lower().strip()
    lines = lyrics.split("\n")

    found = None
    for line in lines:
        line = line.lower().strip()

        if line == query:
            logger.debug("Exact match: %s", line)
            found = line
            break

        if line.startswith(query):
            found = line
            logger.debug("Found line: %s", line)
            break

    if found is not None:
        return found

    result = fuzz_process.extract(query, lines, limit=1)
    logger.debug("Found from fuzz: %s", result)
    return result[0][0]


class SongLyrics(BaseModel):
    id: str
    artist: str
    title: str
    lyrics: str
    model_config = ConfigDict(coerce_numbers_to_str=True)

    @validator("lyrics")
    def fix_lyrics(cls, value):
        if not value:
            return value

        if value.endswith("Embed"):
            return re.sub(r"\d?Embed$", "", value)

        return value


class _LyricsClient:
    def __init__(self, token, proxies=None) -> None:
        self._token = token
        self._genius = Genius(token, proxies=proxies or {})

    @json_cache(load_fn=SongLyrics.model_validate, dump_fn=lambda obj: obj.model_dump())
    def _get_song(self, query):
        if query.startswith(_GENIUS_URL):
            id = self._genius.get_id_from_url(query)
            song = self._genius.search_song(song_id=id)
        else:
            song = self._genius.search_song(query)

        if song is None:
            return None

        song = SongLyrics(
            id=song.id, artist=song.artist, title=song.title, lyrics=song.lyrics
        )

        return song

    def song(self, query: str, line_queries=None):
        song = None
        for _ in range(5):
            try:
                song = self._get_song(query)
                break
            except requests.exceptions.Timeout:
                logger.info("Timeout. Trying again.")

        if song is None:
            logger.debug("No song found")
            return None

        # lyrics = SongLyrics(
        #    id=song.id, artist=song.artist, title=song.title, lyrics=song.lyrics
        # )
        lyrics = song

        if line_queries is not None:
            new_lyrics = ""
            for line_query in line_queries:
                if not new_lyrics:
                    new_lyrics = get_lyrics_line(line_query, lyrics.lyrics)
                else:
                    new_lyrics = (
                        f"{new_lyrics}\n{get_lyrics_line(line_query, lyrics.lyrics)}"
                    )

            lyrics.lyrics = new_lyrics

        return lyrics


class LyricsClient:
    def __init__(self, token: str, proxy_manager: ProxyManager = None):
        self._token = token
        self._proxy_manager = proxy_manager

    @json_cache(load_fn=SongLyrics.model_validate, dump_fn=lambda obj: obj.model_dump())
    def _get_song(self, query):
        def fetch(genius: Genius):
            if query.startswith(_GENIUS_URL):
                song_id = genius.get_id_from_url(query)
                song = genius.search_song(song_id=song_id)
            else:
                song = genius.search_song(query)

            if not song:
                return None

            return SongLyrics(
                id=song.id,
                artist=song.artist,
                title=song.title,
                lyrics=song.lyrics,
            )

        if self._proxy_manager:
            return self._proxy_manager.get_working_genius(fetch)

        genius = Genius(self._token)
        return fetch(genius)

    def song(self, query: str, line_queries=None):
        song = self._get_song(query)
        if song is None:
            logger.debug("No song found")
            return None

        lyrics = song

        if line_queries is not None:
            new_lyrics = ""
            for line_query in line_queries:
                if not new_lyrics:
                    new_lyrics = get_lyrics_line(line_query, lyrics.lyrics)
                else:
                    new_lyrics = (
                        f"{new_lyrics}\n{get_lyrics_line(line_query, lyrics.lyrics)}"
                    )

            lyrics.lyrics = new_lyrics

        return lyrics
