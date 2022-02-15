#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import sqlite3
import logging
from typing import List

from .constants import (
    DISCORD_ANNOUNCER_WEBHOOK,
    DISCORD_TEST_WEBHOOK,
    FB_INFO,
    PATREON,
    TEST,
    WEBSITE,
)
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

    def __init__(self, request: Request, page_url):
        self.request = request
        self.user = request.user
        self.handler = request.get_handler()
        self.post = Post(page_url=page_url, published=not TEST)
        logger.debug("Post instance: %s", self.post)

    def handle(self):
        "Post, register metadata, notify and comment."
        assert self.handler.get()

        self.request.mark_as_used()

        self.post.post(self.post_description, self.images)

        if TEST:
            self._post_webhook()

        self.post.register(self.handler.content)

        for item in self.handler.items:
            item.media.register_post(str(self.post.id))

        self._register_badges()
        self.user.load()

    @property
    def images(self) -> List[str]:
        return self.handler.images

    @property
    def post_description(self) -> str:
        """Description with the handler and request titles.

        :rtype: str
        """
        replacements = _replacements.get(self._replacement_key)
        if not replacements:
            return self.handler.title

        description = self.handler.title

        for replacement_args in replacements:
            description = description.replace(*replacement_args)

        logger.debug("Post description: %s", description)

        return description

    def comment(self):
        "Make the two standard comments."
        first_id = self.post.comment(self._get_info_comment())

        if first_id is not None:
            # story = self.handler.story
            # img_path = os.path.join(gettempdir(), "story.jpg")
            # image = story.get(img_path)

            # badges_str = self._get_badges_comment()
            # self.post.comment(badges_str, first_id)
            pass

    def _register_badges(self):
        assert self.post.id is not None
        to_notify = []
        for badge in self.handler.badges:
            try:
                badge.register(self.user.id, self.post.id)

                if badge.id == 9:
                    continue

                to_notify.append(f"`{badge.name.title()}`")
            except sqlite3.IntegrityError:
                pass

        if to_notify and self.user is not None:
            self.user.load()
            msg = f"`{self.user.name}`'s request is live: {self.post.facebook_url}"
            send_webhook(DISCORD_ANNOUNCER_WEBHOOK, msg)

    def _get_badges_comment(self) -> str:
        badges = self.handler.badges
        badges_len = len(badges)

        if badges_len == 1:
            badge_str = f"🏆 {self.user.name} won one badge:\n{badges[0].fb_reason}"
        else:
            intro = f"🏆 {self.user.name} won {badges_len} badges:\n"
            list_ = "\n".join(badge.fb_reason for badge in badges)
            badge_str = "\n".join((intro, list_))

        return "\n\n".join((badge_str, PATREON))

    def _get_info_comment(self) -> str:
        request_str = self.request.facebook_pretty_title
        movies = [
            item.media for item in self.handler.items if isinstance(item.media, Movie)
        ]
        if movies:
            movie = movies[0]
            movie_str = (
                f"📊 {movie.title}'s community rating: {movie.metadata.rating}.\n"
                f"You can rate any Kinobot movie (e.g. '!rate {movie.simple_title}"
                f" X.X/5')\n\n{FB_INFO}"
            )
            final = f"{request_str}\n\n{movie_str}"
        else:
            final = f"{request_str}\n\n{FB_INFO}"

        return final

    def _post_webhook(self):
        send_webhook(DISCORD_TEST_WEBHOOK, self.post_description, self.images)


class FBPosterEs(FBPoster):
    _replacement_key = "es"
    _FB_INFO = f"💗 Apoya al Kinobot: {PATREON}\n🎬 Explora (~1000 películas): {WEBSITE}"

    def _get_info_comment(self) -> str:
        request_str = self.request.facebook_pretty_title
        movies = [
            item.media for item in self.handler.items if isinstance(item.media, Movie)
        ]
        if movies:
            movie = movies[0]
            movie_str = (
                f"📊 Calificación de {movie.title}: {movie.metadata.rating}.\n"
                f"Puedes calificar cualquier película del Kinobot (ej. '!rate {movie.simple_title}"
                f" X.X/5')\n\n{self._FB_INFO}"
            )
            final = f"{request_str}\n\n{movie_str}"
        else:
            final = f"{request_str}\n\n{self._FB_INFO}"

        return final


class FBPosterPt(FBPoster):
    _replacement_key = "pt"
    _FB_INFO = (
        f"💗 Apoie o Kinobot: {PATREON}\n🎬 Explore a coleção (~1000 filmes): {WEBSITE}"
    )

    def _get_info_comment(self) -> str:
        request_str = self.request.facebook_pretty_title
        movies = [
            item.media for item in self.handler.items if isinstance(item.media, Movie)
        ]
        if movies:
            movie = movies[0]
            movie_str = (
                f"📊 Nota para {movie.title}: {movie.metadata.rating}.\n"
                f"Você pode avaliar qualquer filme do Kinobot (ej. '!rate {movie.simple_title}"
                f" X.X/5')\n\n{self._FB_INFO}"
            )
            final = f"{request_str}\n\n{movie_str}"
        else:
            final = f"{request_str}\n\n{self._FB_INFO}"

        return final


# Too lazy to rewrite now
_replacements = {
    "es": [("Season", "Temporada"), ("Episode", "Episodio")],
    "pt": [("Season", "Temporada"), ("Episode", "Episódio"), ("Director", "Diretor")],
}
