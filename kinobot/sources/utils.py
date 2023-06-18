# -*- coding: utf-8 -*-

import logging
import os
import shutil
import requests
import subprocess
import tempfile

import cv2
import yt_dlp
from PIL import Image

from kinobot import exceptions

logger = logging.getLogger(__name__)


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

                if item["vcodec"] != "vp9":
                    continue

                items.append(item)
        except KeyError:
            raise exceptions.NothingFound(f"Error parsing stream from <{url}>")

    items.sort(key=lambda x: x["quality"], reverse=True)
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
