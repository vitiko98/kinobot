# -*- coding: utf-8 -*-

import logging
import subprocess
import tempfile

import cv2
import yt_dlp

from kinobot import exceptions

from . import registry

logger = logging.getLogger(__name__)


def _get_stream(url):
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
    return items[0]["url"]


def _get_frame_ffmpeg(stream, timestamps):
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
            stream,
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


class MusicVideo:
    "A facade to the awful old interface from kinobot.media"
    type = "song"

    def __init__(self, uri, _model=None):
        self._uri = uri
        self._model = _model
        self._stream = None

    @classmethod
    def from_request(cls, query: str):
        """Get a media subclass by request query.

        :param query:
        :type query: str
        """
        if f"!song" in query:
            return cls

        return None

    @property
    def id(self):
        if self._model:
            return self._model.id

        return self._uri

    @property
    def path(self):
        return self._uri

    @property
    def pretty_title(self) -> str:
        if self._model:
            return self._model.pretty_title()

        return "N/A"

    @property
    def markdown_url(self) -> str:
        return f"[{self.pretty_title}]({self._uri})"

    @property
    def simple_title(self) -> str:
        return self.pretty_title

    @property
    def parallel_title(self) -> str:
        return self.pretty_title

    @property
    def metadata(self):
        return None

    @classmethod
    def from_id(cls, id_):
        result = registry.Repository.from_constants().search(id_)
        return cls(result.uri, result)

    @classmethod
    def from_query(cls, query: str):
        result = registry.Repository.from_constants().search(query)
        return cls(result.uri, result)

    def get_subtitles(self, *args, **kwargs):
        raise exceptions.InvalidRequest("Quotes not supported for songs")

    def get_frame(self, timestamps):
        if self._stream is None:
            self._stream = _get_stream(self._uri)

        return _get_frame_ffmpeg(self._stream, timestamps)

    def register_post(self, post_id):
        pass
