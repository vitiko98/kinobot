# -*- coding: utf-8 -*-
import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import List

import cv2
import numpy as np
from PIL import Image
import pydantic
import requests
import yt_dlp

from kinobot import exceptions

logger = logging.getLogger(__name__)

_cache_filename = os.path.join(tempfile.gettempdir(), f"{__name__}.cache")


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

                logger.debug("Video format: %s", json.dumps(item, indent=4))

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

    return YtdlpItem(
        id=info["id"],
        title=info.get("title"),
        uploader=info.get("uploader"),
        stream_url=stream_url,
        subtitles=subs,
    )


def get_stream(url):
    "raises exceptions.NothingFound"
    ydl_opts = {
        "format": "bv",
    }

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


def get_frame_ffmpeg(input_, timestamps):
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
