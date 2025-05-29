# -*- coding: utf-8 -*-

import hashlib
import logging

from kinobot import exceptions

from . import registry
from .. import utils
from ..abstract import AbstractMedia

logger = logging.getLogger(__name__)


class SportsMatch(AbstractMedia):
    type = "sports"

    def __init__(self, uri, _model=None):
        self._uri: str = uri
        self._model = _model
        self._stream = None

    @classmethod
    def from_request(cls, query: str):
        if f"!sports" in query:
            return cls

        return None

    @property
    def id(self):
        return hashlib.md5(self._uri.encode()).hexdigest()

    @property
    def path(self):
        return self._uri

    @property
    def pretty_title(self) -> str:
        if self._model is not None:
            return f"{self._model.title}\n{self._model.tournament}"

        return "N/A"

    @property
    def markdown_url(self) -> str:
        return f"[{self.pretty_title}]({self._uri})"

    @property
    def simple_title(self) -> str:
        return self.parallel_title

    @property
    def parallel_title(self) -> str:
        if self._model:
            return f"{self._model.title} ({self._model.tournament})"

        return "N/A"

    @property
    def metadata(self):
        return None

    @classmethod
    def from_id(cls, id_):
        return cls.from_query(id_)  # fixme

    @classmethod
    def from_query(cls, query: str, repository=None):
        if repository is None:
            repository = registry.Repository.from_db_url()

        item = repository.fuzzy_search(query.strip())
        if item is None:
            raise exceptions.NothingFound

        return cls(item.uri, item)

    def get_subtitles(self, *args, **kwargs):
        raise exceptions.InvalidRequest("Quotes not supported for sports")

    def get_frame(self, timestamps):
        proxy_manager = utils.ProxyManager(config.proxy_file)

        if self._stream is None:
            self._stream = utils.get_ytdlp_item_advanced(self._uri, proxy_manager)
            logger.info(self._stream)

        file_ = utils.get_frame_file_ffmpeg(
            self._stream.stream_url, timestamps, proxy_manager, self._stream.id
        )
        return utils.img_path_to_cv2([file_])[0]

    def register_post(self, post_id):
        pass
