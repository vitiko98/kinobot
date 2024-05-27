# -*- coding: utf-8 -*-

import logging

from kinobot import exceptions

from . import registry
from .. import utils
from ..abstract import AbstractMedia

logger = logging.getLogger(__name__)


class GameCutscene(AbstractMedia):
    "A facade to the awful old interface from kinobot.media"
    type = "game"

    def __init__(self, uri, _game_model=None, _cs_model=None):
        self._uri = uri
        self._game_model = _game_model
        self._cs_model = _cs_model
        self._stream = None

    @classmethod
    def from_request(cls, query: str):
        if f"!game" in query:
            return cls

        return None

    @property
    def id(self):
        if self._cs_model is not None:
            return f"{self._cs_model.game_id}_{self._cs_model.id}"

        return self._uri

    @property
    def path(self):
        return self._uri

    @property
    def pretty_title(self) -> str:
        if self._game_model is not None:
            title = self._game_model.pretty_title()

            if self._game_model.company_objects:
                title = f'{title}\n{", ".join(company.name for company in self._game_model.company_objects)}'

            return title

        return "N/A"

    @property
    def markdown_url(self) -> str:
        return f"[{self.pretty_title}]({self._uri})"

    @property
    def simple_title(self) -> str:
        return self.parallel_title

    @property
    def parallel_title(self) -> str:
        if self._game_model:
            return self._game_model.pretty_title()

        return "N/A"

    @property
    def metadata(self):
        return None

    @classmethod
    def from_id(cls, id_):
        return cls.from_query(id_)  # fixme

    @classmethod
    def from_query(cls, query: str):
        repo = registry.Repository.from_constants()

        cutscene_ = repo.search_cutscene(query)
        game_ = repo.from_game_id(cutscene_.game_id)

        return cls(cutscene_.uri, game_, cutscene_)

    def get_subtitles(self, *args, **kwargs):
        raise exceptions.InvalidRequest("Quotes not supported for games")

    def get_frame(self, timestamps):
        if self._stream is None:
            self._stream = utils.get_stream(self._uri)

        return utils.get_frame_ffmpeg(self._stream, timestamps)

    def register_post(self, post_id):
        pass
