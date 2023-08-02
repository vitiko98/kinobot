# -*- coding: utf-8 -*-
import datetime
import srt

import logging

from kinobot import exceptions
from kinobot.constants import YAML_CONFIG
from kinobot.utils import get_yaml_config
from kinobot.playhouse.lyric_card import SongLyrics, LyricsClient

from .. import abstract
from .. import utils

logger = logging.getLogger(__name__)


class Lyrics(abstract.AbstractMedia):
    "A facade to the awful old interface from kinobot.media"
    type = "lyrics"

    def __init__(self, _model: SongLyrics):
        self._model = _model  # type: SongLyrics

    @classmethod
    def from_request(cls, query: str):
        """Get a media subclass by request query.

        :param query:
        :type query: str
        """
        if f"!lyrics" in query:
            return cls

        return None

    @property
    def id(self):
        return self._model.id

    @property
    def path(self):
        return self._model.id

    @property
    def pretty_title(self) -> str:
        return f'{self._model.artist}, "{self._model.title}"'

    @property
    def markdown_url(self) -> str:
        return f"[{self.pretty_title}]({self.id})"

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
        return cls.from_query(id_)

    @classmethod
    def from_query(cls, query: str):
        client = make_client()
        song = client.song(query)
        if song is None:
            raise exceptions.NothingFound

        return cls(song)

    def get_subtitles(self, *args, **kwargs):
        subs = []
        for n, line in enumerate(self._model.lyrics.split("\n")):
            subs.append(
                srt.Subtitle(
                    index=n,
                    start=datetime.timedelta(seconds=n + 1),
                    end=datetime.timedelta(seconds=n + 2),
                    content=line,
                )
            )

        return subs

    def get_frame(self, timestamps):
        return utils.cv2_color_image()

    def register_post(self, post_id):
        pass


def make_client():
    return LyricsClient(get_yaml_config(YAML_CONFIG or "", "genius")["token"])
