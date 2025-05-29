# -*- coding: utf-8 -*-
import logging

import srt

from kinobot import exceptions
from kinobot.config import config

from .. import abstract
from .. import utils

logger = logging.getLogger(__name__)

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
    "proxy": config.ytdlp.proxy,
}


def _get_proxy_manager(proxy_path=None):
    return utils.ProxyManager(proxy_path or config.proxy_file)


class YTVideo(abstract.AbstractMedia):
    type = "yt"

    def __init__(self, item, proxy_manager=None):
        self._item = item
        self._proxy_manager = proxy_manager or utils.ProxyManager(
            proxy_file=config.proxy_file
        )
        logger.debug("Item: %s", self._item)

    @classmethod
    def from_request(cls, query: str):
        if f"!yt" in query:
            return cls

        return None

    @property
    def id(self):
        return self._item.id

    @property
    def path(self):
        return self._item.stream_url

    @property
    def pretty_title(self) -> str:
        title = self._item.title
        if self._item.uploader:
            title = f"{title}\nby {self._item.uploader}"

        return title

    @property
    def markdown_url(self) -> str:
        return f"[{self.pretty_title}]({self.id})"

    @property
    def simple_title(self) -> str:
        return self.parallel_title

    @property
    def parallel_title(self) -> str:
        return self._item.title

    @property
    def metadata(self):
        return None

    @classmethod
    def from_id(cls, id):
        pm = _get_proxy_manager()
        return cls(utils.get_ytdlp_item_advanced(id, pm), pm)

    @classmethod
    def from_query(cls, query: str):
        pm = _get_proxy_manager()
        return cls(utils.get_ytdlp_item_advanced(query, pm), pm)

    def get_subtitles(self, *args, **kwargs):
        sub_path = utils.get_subtitle(self._item)

        with open(sub_path, "r") as item:
            try:
                return list(srt.parse(item))
            except (srt.TimestampParseError, srt.SRTParseError) as error:
                raise exceptions.SubtitlesNotFound(
                    "The subtitles are corrupted. Please report this to the admin."
                ) from error

    def get_frame(self, timestamps):
        img = utils.get_frame_file_ffmpeg(
            self._item.stream_url, timestamps, self._proxy_manager, self._item.id
        )
        return utils.img_path_to_cv2([img])[0]

    def register_post(self, post_id):
        pass
