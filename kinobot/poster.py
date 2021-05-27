#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import sqlite3
from typing import List

from .constants import (DISCORD_ANNOUNCER_WEBHOOK, DISCORD_TEST_WEBHOOK,
                        FB_INFO, PATREON)
from .db import Kinobase
from .media import Movie
from .post import Post
from .request import Request
from .utils import send_webhook


class FBPoster(Kinobase):
    "Class for generated Facebook posts."

    def __init__(self, request: Request):
        self.request = request
        self.user = request.user
        self.handler = request.get_handler()
        self.test = self.__database__.endswith(".save")
        self.post = Post(published=not self.test)

    def handle(self):
        "Post, register metadata, notify and comment."
        assert self.handler.get()

        self.request.mark_as_used()

        self.post.post(self.post_description, self.images)

        if self.test:
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
        # Avoid showing the request data in the first post impression
        title_lines = len(self.handler.title.split("\n"))

        final_split = "\n\n"
        if title_lines < 3:
            final_split = "\n\n\n\n"

        return final_split.join(
            (self.handler.title, self.request.facebook_pretty_title)
        )

    def comment(self):
        "Make the two standard comments."
        first_id = self.post.comment(self._get_info_comment())

        if first_id is not None:
            # story = self.handler.story
            # img_path = os.path.join(gettempdir(), "story.jpg")
            # image = story.get(img_path)

            badges_str = self._get_badges_comment()
            self.post.comment(badges_str, first_id)

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

        if to_notify:
            msg = f"`{self.user.name}` just won: {', '.join(to_notify)}."
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
        movies = [
            item.media for item in self.handler.items if isinstance(item.media, Movie)
        ]
        rate_str = FB_INFO
        if movies:
            movie = movies[0]
            rate_str = (
                f"📊 {movie.title}'s community rating: {movie.metadata.rating}.\n"
                f"You can rate any Kinobot movie (e.g. '!rate {movie.simple_title}"
                f" X.X/5')\n\n{FB_INFO}"
            )

        return rate_str

    def _post_webhook(self):
        send_webhook(DISCORD_TEST_WEBHOOK, self.post_description, self.images)
