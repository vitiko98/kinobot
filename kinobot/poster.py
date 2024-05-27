#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import sqlite3
from typing import List

from .constants import DISCORD_ANNOUNCER_WEBHOOK
from .constants import DISCORD_TEST_WEBHOOK
from .constants import FB_INFO
from .constants import PATREON
from .constants import TEST
from .constants import WEBSITE
from .db import Kinobase
from .media import Movie
from .post import Post
from .request import Request
from .utils import send_webhook

logger = logging.getLogger(__name__)


class FBPoster(Kinobase):
    "Class for generated Facebook posts."
    _FB_INFO = f"💗 Support Kinobot: {PATREON}\n🎬 Explore the collection (~1000 movies): {WEBSITE}"
    _replacement_key = "en"

    def __init__(self, request: Request, post_instance: Post):
        self.request = request
        self.user = request.user
        self.handler = request.get_handler()
        self.post = post_instance
        self._attributions = []
        logger.debug("Post instance: %s", self.post)

    def handle(self):
        "Post, register metadata, notify and comment."
        assert self.handler.get()

        for item in self.handler.items:
            try:
                if item.media.attribution:  # type:ignore
                    self._attributions.append(item.media.attribution)
            except:  # fixme
                pass

        self.post.post(self.post_description, self.images)

        self.request.mark_as_used()

        self.post.register(self.request.id)

        for item in self.handler.items:
            item.media.register_post(self.post.id)

        self.user.load()

        self._notify()

    @property
    def images(self) -> List[str]:
        return self.handler.images

    @property
    def post_description(self) -> str:
        """Description with the handler and request titles.

        :rtype: str
        """
        replacements = _replacements.get(self._replacement_key)
        description = self.handler.title

        if replacements is not None:
            for replacement_args in replacements:
                description = description.replace(*replacement_args)

        description = (
            f"{description}\n.\n.\n.\n.\n.\n{self.request.facebook_pretty_title}"
        )
        if self._attributions:
            self._attributions = set(self._attributions)
            description = f"{description}\n\nCredits: {', '.join(self._attributions)}"

        logger.debug("Post description: %s", description)

        return description

    def comment(self):
        "Make the two standard comments."
        # Temporary
        return None

    def _notify(self):
        # fixme: this is awful
        if self.user is not None:
            self.user.load()
            msg = f"`{self.user.name}`'s request is live: {self.post.facebook_url}"
            send_webhook(DISCORD_ANNOUNCER_WEBHOOK, msg)

    def _get_info_comment(self) -> str:
        movies = [
            item.media for item in self.handler.items if isinstance(item.media, Movie)
        ]
        if movies:
            movie = movies[0]
            final = (
                f"📊 {movie.title}'s community rating: {movie.metadata.rating}.\n"
                f"(!rate {movie.simple_title}"
                f" X.X/5)\n\n{FB_INFO}"
            )
        else:
            final = self._FB_INFO

        return f"{final}\n\n{self.request.facebook_pretty_title}"


class FBPosterEs(FBPoster):
    _replacement_key = "es"
    _FB_INFO = f"💗 Apoya al Kinobot: {PATREON}\n🎬 Explora (~1000 películas): {WEBSITE}"

    def _get_info_comment(self) -> str:
        movies = [
            item.media for item in self.handler.items if isinstance(item.media, Movie)
        ]
        if movies:
            movie = movies[0]
            final = (
                f"📊 Calificación de {movie.title}: {movie.metadata.rating}.\n"
                f"(!rate {movie.simple_title}"
                f" X.X/5)\n\n{self._FB_INFO}"
            )
        else:
            final = self._FB_INFO

        return f"{final}\n\n{self.request.facebook_pretty_title}"


class FBPosterPt(FBPoster):
    _replacement_key = "pt"
    _FB_INFO = (
        f"💗 Apoie o Kinobot: {PATREON}\n🎬 Explore a coleção (~1000 filmes): {WEBSITE}"
    )

    def _get_info_comment(self) -> str:
        movies = [
            item.media for item in self.handler.items if isinstance(item.media, Movie)
        ]
        if movies:
            movie = movies[0]
            final = (
                f"📊 Nota para {movie.title}: {movie.metadata.rating}.\n"
                f"(!rate {movie.simple_title}"
                f" X.X/5)\n\n{self._FB_INFO}"
            )
        else:
            final = self._FB_INFO

        return f"{final}\n\n{self.request.facebook_pretty_title}"


# Too lazy to rewrite now
_replacements = {
    "es": [("Season", "Temporada"), ("Episode", "Episodio")],
    "pt": [("Season", "Temporada"), ("Episode", "Episódio"), ("Director", "Diretor")],
}
