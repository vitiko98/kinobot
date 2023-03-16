# -*- coding: utf-8 -*-

import hashlib
import logging

from kinobot import exceptions

from . import registry
from .. import utils
from ..abstract import AbstractMedia

logger = logging.getLogger(__name__)


class MangaPage(AbstractMedia):
    type = "manga"

    def __init__(self, uri, _manga_model=None, _chapter_model=None, _page_model=None):
        self._uri = uri
        self._stream = None
        self._manga_model = _manga_model
        self._chapter_model = _chapter_model

    @classmethod
    def from_request(cls, query: str):
        if f"!manga" in query:
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
        if not self._manga_model or not self._chapter_model:
            return self._uri

        title = self._manga_model.pretty_title()
        authors = []
        for rel in self._manga_model.relationships:
            if rel.type == "author":
                authors.append(rel.name)

        if authors:
            authors = _grammatically_join(authors)

        if authors:
            return f"{title}\nby {authors}"

        return title

    @property
    def markdown_url(self) -> str:
        raise NotImplementedError

    @property
    def simple_title(self) -> str:
        return self.parallel_title

    @property
    def parallel_title(self) -> str:
        if self._manga_model is not None:
            return self._manga_model.pretty_title()

        return "Unknown"

    @property
    def metadata(self):
        return None

    @classmethod
    def from_id(cls, id_):
        return cls.from_query(id_)  # fixme

    @classmethod
    def from_query(cls, query: str, repo=None):
        query_ = registry.MangaQuery.from_str(query)
        if query_.page is None or query_.chapter is None:
            raise exceptions.InvalidRequest(
                "Chapter and page numbers are required (MANGA CHAPTER 1 PAGE 1)"
            )

        logger.debug("Query: %s", query_)

        repo = repo or registry.Repository.from_constants()

        if query_.id is not None:
            manga = repo.from_manga_id(query_.id)
        else:
            manga_id = repo.search_manga(query_.title or "")
            manga = repo.from_manga_id(manga_id)

        try:
            chapter = int(query_.chapter)
            chapter = repo.get_chapters(manga.id, query_.chapter)[0]
        except ValueError:
            chapter = repo.get_chapter(query_.chapter)

        pages = registry.Client().get_chapter_pages(chapter.id)
        try:
            page = [page for page in pages if page.page_number == query_.page][0]
        except IndexError:
            raise registry.MangaNotFound(f"Page {query_.page} not found")

        return cls(page.url, manga, chapter, page)

    def get_subtitles(self, *args, **kwargs):
        raise exceptions.InvalidRequest("Quotes not supported for mangas")

    def get_frame(self, timestamps):
        return utils.get_http_image(self._uri)

    def register_post(self, post_id):
        pass

    @property
    def attribution(self):
        return f"Manga pages from MangaDex"


def _grammatically_join(words):
    if len(words) == 0:
        return ""
    if len(words) == 1:
        return words[0]

    return f'{", ".join(words[:-1])} and {words[-1]}'
