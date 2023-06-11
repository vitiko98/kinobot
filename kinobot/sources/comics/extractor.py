# -*- coding: utf-8 -*-

import hashlib
import logging

from kinobot import exceptions

from . import client as comic_client
from .. import utils
from ..abstract import AbstractMedia
from .client import ComicQuery

logger = logging.getLogger(__name__)


class ComicPage(AbstractMedia):
    type = "comic"

    def __init__(
        self, uri, model: comic_client.Series, chapter_model: comic_client.Chapter
    ):
        self._uri = uri
        self._stream = None
        self._chapter_model = chapter_model
        self._model = model

    @classmethod
    def from_request(cls, query: str):
        if f"!comic" in query:
            return cls

        return None

    @property
    def id(self):
        return hashlib.md5(self._uri.encode("utf-8")).hexdigest()

    @property
    def path(self):
        return self.id

    @property
    def pretty_title(self) -> str:
        title = self.simple_title

        if self._model.metadata is not None:
            publishers = self._model.metadata.publishers
            if publishers:
                publishers = _grammatically_join([item.name for item in publishers])
                title = f"{title}\n{publishers}"

        return title

    @property
    def markdown_url(self) -> str:
        raise NotImplementedError

    @property
    def simple_title(self) -> str:
        title = self._model.name
        if self._chapter_model.title:
            title = f"{title} [{self._chapter_model.title}]"
        elif self._chapter_model.number:
            title = f"{title} [#{self._chapter_model.number}]"

        return title

    @property
    def parallel_title(self) -> str:
        return self.simple_title

    @property
    def metadata(self):
        return None

    @classmethod
    def from_id(cls, id_):
        return cls.from_query(id_)  # fixme

    @classmethod
    def from_query(cls, query: str, client=None):
        query_ = ComicQuery.from_str(query)
        if query_.page is None or query_.chapter is None:
            raise exceptions.InvalidRequest(
                "Chapter/Issue and page numbers are required (COMIC CHAPTER 1 PAGE 1)"
            )

        logger.debug("Query: %s", query_)

        client = client or comic_client.Client.from_config()

        if query_.id is not None:
            comic = client.get_series(query_.id)
        else:
            comic = client.first_series_matching(query_.title)
            if not comic:
                raise exceptions.NothingFound(f"Not found: {query_}")

        logger.debug("Comic found: %s", comic)

        chapter = [
            chapter
            for chapter in comic.chapters
            if str(chapter.number) == str(query_.chapter)
        ]
        if not chapter:
            raise exceptions.NothingFound(f"Chapter not found: {query_}")

        chapter = chapter[0]

        if query_.page > chapter.pages:
            raise exceptions.NothingFound(
                f"This chapter only has {chapter.pages} pages"
            )

        return cls(
            uri=client.image_url(chapter.id, query_.page),
            model=comic,
            chapter_model=chapter,
        )

    def get_subtitles(self, *args, **kwargs):
        raise exceptions.InvalidRequest("Quotes not supported for comics")

    def get_frame(self, timestamps):
        return utils.get_image_from_download_url(self._uri)

    def register_post(self, post_id):
        pass

    @property
    def attribution(self):
        return f"Metadata from ComicVine"



def _grammatically_join(words):
    if len(words) == 0:
        return ""
    if len(words) == 1:
        return words[0]

    return f'{", ".join(words[:-1])} and {words[-1]}'
