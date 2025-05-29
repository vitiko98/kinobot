# -*- coding: utf-8 -*-
import hashlib
import json
import logging
from functools import wraps

import os
import shutil
import subprocess
import tempfile
from typing import List, Optional
from urllib.parse import urlparse, parse_qs, urlencode

from kinobot.config import config

import cv2
import numpy as np
from PIL import Image
import pydantic
import requests
import yt_dlp

from kinobot import exceptions

import os
import time
import random
import requests


logger = logging.getLogger(__name__)

_cache_filename = os.path.join(tempfile.gettempdir(), f"{__name__}.cache")

_ydl_opts = {
    #    "quiet": True,
    "force_generic_extractor": True,
    "extract_flat": True,
    "writesubtitles": True,
    "subtitleslangs": ["en"],
    # "username": "oauth2",
    # "password": "",
    # "cachedir": config.ytdlp.cache_dir,
    "cookies": config.ytdlp.cookies,
    #    "proxy": config.ytdlp.proxy,
}


class ProxyManager:
    def __init__(
        self,
        proxy_file: str,
        max_retries: int = 5,
        backoff_base: float = 0.5,
        max_proxies=15,
    ):
        self._proxy_file = proxy_file
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._max_proxies = max_proxies
        self._last_good_proxy = None
        self._blacklist = set()
        self._proxies = self._load_proxies()

    def _load_proxies(self):
        if not os.path.exists(self._proxy_file):
            raise FileNotFoundError(f"Proxy file not found: {self._proxy_file}")

        with open(self._proxy_file, "r") as f:
            lines = [line.strip() for line in f if line.strip()]

        random.shuffle(lines)
        proxies = []

        for line in lines:
            parts = line.split(":")
            if len(parts) == 4:
                ip, port, user, password = parts
                proxy_str = f"http://{user}:{password}@{ip}:{port}"
            elif len(parts) == 2:
                ip, port = parts
                proxy_str = f"http://{ip}:{port}"
            else:
                continue  # Invalid format
            proxies.append({"http": proxy_str, "https": proxy_str})

        return proxies

    def _proxy_repr(self, proxy):
        return proxy["http"] if proxy else "no_proxy"

    def _blacklist_proxy(self, proxy):
        self._blacklist.add(self._proxy_repr(proxy))

    def _backoff(self, attempt):
        time.sleep(self._backoff_base * (2**attempt))

    def get_last_working_proxy(self):
        if self._last_good_proxy is None:
            logger.info("No good proxy set yet. Looking for one...")

            assert get_ytdlp_item_advanced(
                "https://www.youtube.com/watch?v=QkkoHAzjnUs", self
            )

        return self._last_good_proxy

    def get_working_proxy(self, fn):
        attempts = 0
        proxy_count = 0
        last_error = None
        tried = set()

        def try_proxy(proxy):
            nonlocal attempts, last_error

            if attempts >= self._max_retries:
                return None

            key = self._proxy_repr(proxy)
            if key in tried or key in self._blacklist:
                return None
            tried.add(key)

            try:
                result = fn(proxy)
                self._last_good_proxy = proxy
                return result
            except BadInputError:
                raise exceptions.InvalidRequest(
                    "Timestamp not found. This error is not related to a bad connection."
                )
            except requests.exceptions.Timeout:
                self._blacklist_proxy(proxy)
                self._backoff(attempts)
                attempts += 1
                last_error = requests.exceptions.Timeout()
            except Exception as exc:
                logger.exception(exc)
                self._blacklist_proxy(proxy)
                attempts += 1
                last_error = exc
            return None

        if self._last_good_proxy:
            result = try_proxy(self._last_good_proxy)
            if result:
                return result

        for proxy in self._proxies:
            if proxy_count >= self._max_proxies:
                logger.info("Proxy count limit hit: %d", self._max_proxies)
                break
            if attempts >= self._max_retries:
                break

            proxy_count += 1
            result = try_proxy(proxy)
            if result:
                return result

        raise last_error or RuntimeError("All proxy attempts failed")


def _clean_yt_url(url):
    if "yt" not in url or "youtube" not in url:
        return url

    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)

    if "v" in query_params:
        clean_query = {"v": query_params["v"]}
        new_query_string = urlencode(clean_query, doseq=True)
        clean_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}?{new_query_string}"
    else:
        clean_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

    return clean_url


class VideoSubtitlesNotFound(exceptions.KinoException):
    pass


class YtdlpSubtitle(pydantic.BaseModel):
    url: str
    ext: str


class YtdlpItem(pydantic.BaseModel):
    title: str
    uploader: str = "Unknown"
    subtitles: List[YtdlpSubtitle] = []
    stream_url: str
    id: str
    frames: List[str] = []


def _download_sub(url, video_id):
    path = os.path.join(tempfile.gettempdir(), f"{video_id}.vtt")
    srt_path = os.path.join(tempfile.gettempdir(), f"{video_id}.srt")

    if os.path.exists(srt_path):
        logger.info("Subtitle file already saved: %s", srt_path)
        return srt_path

    r = requests.get(url)
    r.raise_for_status()

    with open(path, "wb") as f:
        f.write(r.content)

    command = ["ffmpeg", "-i", path, srt_path]

    logger.debug("Command to run: %s", " ".join(command))
    try:
        subprocess.run(command, timeout=1000)
    except subprocess.TimeoutExpired as error:
        raise exceptions.KinoUnwantedException("Subprocess error") from error

    return srt_path


def get_subtitle(item: YtdlpItem):
    found = None
    for sub in item.subtitles:
        if sub.ext == "vtt":
            found = sub
            break

    if found is None:
        raise VideoSubtitlesNotFound(
            "This video doesn't have any english subtitles available"
        )

    return _download_sub(found.url, item.id)


def get_ytdlp_item(url, options):
    "raises exceptions.NothingFound"
    items = []
    items_mp4 = []

    url = _clean_yt_url(url)

    with yt_dlp.YoutubeDL(options) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            info = ydl.sanitize_info(info)  # type: dict
        except yt_dlp.utils.DownloadError:
            raise exceptions.NothingFound(f"Stream not found for <{url}>")

        try:
            for item in info["formats"]:
                if item["video_ext"] == "none":
                    continue

                if not item.get("filesize"):
                    continue

                note = item.get("format_note", "n/a").lower()
                if "throttled" in note:
                    continue

                # logger.debug("Video format: %s", json.dumps(item, indent=4))

                if item.get("vcodec", "n/a").startswith("vp"):
                    items.append(item)

                if item.get("video_ext", "n/a").startswith("mp4"):
                    items_mp4.append(item)

        except KeyError:
            raise exceptions.NothingFound(f"Error parsing stream from <{url}>")

    items.sort(key=lambda x: x["filesize"], reverse=True)
    items_mp4.sort(key=lambda x: x["filesize"], reverse=True)

    try:
        stream_url = items[0]["url"]
    except IndexError:
        logger.debug("Falling back to mp4")
        try:
            stream_url = items_mp4[0]["url"]
        except IndexError:
            raise exceptions.FailedQuery(
                "Couldn't get url stream from video. "
                "Please try again later of report this source."
            )

    subs = []
    for key, sub in info.get("subtitles", {}).items():
        if key == "en" or key.startswith("en-"):
            for sub_ in sub:
                subs.append(YtdlpSubtitle(**sub_))
        else:
            logger.debug("Skipping %s subtitles", key)

    frames = []
    # for timestamp in timestamp_list:
    #    logger.debug("Getting %s", options)
    #    frame_ = get_frame_file_ffmpeg(stream_url, timestamp, options)
    #    frames.append(frame_)

    return YtdlpItem(
        id=info["id"],
        title=info.get("title"),
        uploader=info.get("uploader"),
        stream_url=stream_url,
        subtitles=subs,
        frames=frames,
    )


def get_ytdlp_item_advanced(url, proxy_manager, ydl_opts=None):
    ydl_opts = ydl_opts or _ydl_opts

    def try_proxy(proxy):
        if proxy:
            ydl_opts["proxy"] = proxy["http"]

        return get_ytdlp_item(url, ydl_opts)  # YtdlpItem (pydantic model)

    return proxy_manager.get_working_proxy(try_proxy)


def get_stream(url):
    "raises exceptions.NothingFound"
    ydl_opts = {
        "format": "bv",
    }
    url = _clean_yt_url(url)

    items = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            info = ydl.sanitize_info(info)
        except yt_dlp.utils.DownloadError:
            raise exceptions.NothingFound(f"Stream not found for <{url}>")

        try:
            for item in info["formats"]:
                if item["video_ext"] == "none":
                    continue

                if not item.get("vcodec", "n/a").startswith("vp"):
                    continue

                if not item.get("filesize"):
                    continue

                items.append(item)
        except KeyError:
            raise exceptions.NothingFound(f"Error parsing stream from <{url}>")

    items.sort(key=lambda x: x["filesize"], reverse=True)

    try:
        return items[0]["url"]
    except IndexError:
        raise exceptions.FailedQuery(
            "Couldn't get url stream from video. "
            "Please try again later of report this source."
        )


def get_image_from_download_url(url):
    response = requests.get(url, allow_redirects=True)
    response.raise_for_status()

    with tempfile.NamedTemporaryFile(
        prefix="kinobot", suffix=os.path.splitext(url)[-1]
    ) as named:
        with open(named.name, "wb") as file:
            file.write(response.content)

        frame = cv2.imread(named.name)

        if frame is None:
            raise exceptions.NothingFound("Couldn't extract image")

        return frame


def img_path_to_cv2(imgs):
    return [cv2.imread(path) for path in imgs]


def get_http_image(url):
    response = requests.get(url, stream=True)
    response.raise_for_status()

    with tempfile.NamedTemporaryFile(
        prefix="kinobot", suffix=os.path.splitext(url)[-1]
    ) as named:
        with open(named.name, "wb") as out_file:
            shutil.copyfileobj(response.raw, out_file)

        frame = cv2.imread(named.name)

        if frame is None:
            raise exceptions.NothingFound("Couldn't extract image")

        return frame


def cv2_color_image(dimensions=(500, 500), color=(255, 255, 255)):
    image = np.zeros((dimensions[0], dimensions[1], 3), np.uint8)
    color = tuple(reversed(color))
    image[:] = color

    return image


class SourceError(Exception):
    pass


class BadInputError(SourceError):
    pass


class ProxyError(SourceError):
    pass


_bad_imgs = (
    "Output file is empty",
    "Invalid argument",
    "output file is empty",
    "No filtered frames",
)


def file_cache(expire_seconds=None, cache_dir=None):
    cache_dir = cache_dir or os.path.join(tempfile.gettempdir(), "kinobot_cache")
    os.makedirs(cache_dir, exist_ok=True)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            timestamps = kwargs.get("timestamps", None)
            cache_reference = kwargs.get("cache_reference", None)

            if timestamps is None or cache_reference is None:
                if len(args) >= 2:
                    timestamps = timestamps or args[1]
                if len(args) >= 4:
                    cache_reference = cache_reference or args[3]

            if timestamps is None or cache_reference is None:
                raise ValueError(
                    "timestamps and cache_reference must be provided for caching"
                )

            key = f"{cache_reference}_{timestamps}"
            # Hash the key for filename safety
            hashed_key = hashlib.sha256(key.encode()).hexdigest()
            cache_filename = os.path.join(cache_dir, f"{hashed_key}.png")

            if os.path.exists(cache_filename):
                if expire_seconds is None:
                    logger.debug("Already cached file: %s", cache_filename)
                    return cache_filename
                age = time.time() - os.path.getmtime(cache_filename)
                if age < expire_seconds:
                    return cache_filename

            result_filepath = func(*args, **kwargs)
            shutil.move(result_filepath, cache_filename)
            logger.debug("Cached file: %s", cache_filename)
            return cache_filename

        return wrapper

    return decorator


@file_cache()
def get_frame_file_ffmpeg(
    input_,
    timestamps,
    proxy_manager: Optional[ProxyManager] = None,
    cache_reference=None,
):
    ffmpeg_ts = ".".join(str(int(ts)) for ts in timestamps)
    with tempfile.NamedTemporaryFile(
        prefix="kinobot", suffix=".png", delete=False
    ) as named:
        command = [
            "ffmpeg",
            "-y",
            #    "-v",
            #    "quiet",
            "-stats",
            "-ss",
            ffmpeg_ts,
        ]

        if proxy_manager is not None:
            proxy_url = proxy_manager.get_last_working_proxy()
            if proxy_url:
                command.extend(["-http_proxy", str(proxy_url["http"])])

        command.extend(
            [
                "-i",
                input_,
                "-vf",
                "scale=iw*sar:ih",
                "-vframes",
                "1",
                str(named.name),
            ]
        )

        logger.debug("Command to run: %s", " ".join(command))

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=12000,
            )
        except subprocess.CalledProcessError as e:
            err = f"\n\n{e.stderr}\n{e.stdout}\n\n"
            logger.error("FFmpeg failed: %s", err)

            if "404 Not Found" in err or "403 Forbidden" in err:
                raise ProxyError("Connection failed (possibly due to proxy)")

            if any(b.lower() in err.lower() for b in _bad_imgs):
                raise BadInputError(f"Timestamp `{timestamps}` not found")

            raise exceptions.KinoUnwantedException("FFmpeg failed") from e

        except subprocess.TimeoutExpired as error:
            raise exceptions.KinoUnwantedException("FFmpeg timed out") from error

        if any(
            b.lower() in (str(result.stderr) + str(result.stdout)).lower()
            for b in _bad_imgs
        ):
            raise BadInputError(f"Timestamp `{timestamps}` not found")

        logger.debug(result.stderr)
        logger.debug(result.stdout)
        return named.name


def get_frame_ffmpeg(input_, timestamps, proxy=False, proxy_raw=None):
    ffmpeg_ts = ".".join(str(int(ts)) for ts in timestamps)
    with tempfile.NamedTemporaryFile(prefix="kinobot", suffix=".png") as named:
        command = [
            "ffmpeg",
            "-y",
            "-v",
            "quiet",
            "-stats",
            "-ss",
            ffmpeg_ts,
            "-i",
            input_,
            "-vf",
            "scale=iw*sar:ih",
            "-vframes",
            "1",
            named.name,
        ]

        logger.debug("Command to run: %s", " ".join(command))
        try:
            subprocess.run(command, timeout=12000)
        except subprocess.TimeoutExpired as error:
            raise exceptions.KinoUnwantedException("Subprocess error") from error

        frame = cv2.imread(named.name)
        if frame is not None:
            logger.debug("OK")
            return frame

        raise exceptions.InexistentTimestamp(f"`{timestamps}` timestamp not found")
