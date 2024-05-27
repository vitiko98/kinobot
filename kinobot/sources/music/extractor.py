# -*- coding: utf-8 -*-

import logging

from kinobot import exceptions

from . import registry
from .. import abstract
from .. import utils

logger = logging.getLogger(__name__)


class MusicVideo(abstract.AbstractMedia):
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
            return f"{self._model.name}\nby {self._model.artist}"

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
            return self._model.pretty_title()

        return "N/A"

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
            self._stream = utils.get_stream(self._uri)

        return utils.get_frame_ffmpeg(self._stream, timestamps)

    def register_post(self, post_id):
        pass
