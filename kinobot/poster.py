#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import os
from tempfile import gettempdir

from typing import List
from discord_webhook import DiscordWebhook
from .constants import FB_INFO, PATREON, DISCORD_WEBHOOK_TEST
from .db import Kinobase
from .media import Movie
from .post import Post
from .request import Request


class FBPoster(Kinobase):
    def __init__(self, request: Request, test: bool = True):
        self.request = request
        self.user = request.user
        self.test = test
        self.handler = request.get_handler()
        self.post = Post(published=not test)

    def handle(self):
        " Post, register metadata, notify and comment. "
        self.post.post(self.handler)

        if self.test:
            self._discord_webhook(self.handler.title, self.post.images)
        # Register the post
        self.post.register()

        for item in self.handler.items:
            item.media.register_post(self.post.id)  # type: ignore

        self._register_badges()
        self.user.load()

    def comment(self):
        story = self.handler.story
        img_path = os.path.join(gettempdir(), "story.jpg")
        image = story.get(img_path)

        badges_str = self._get_first_comment()

        if self.test:
            self._discord_webhook(badges_str.replace(PATREON, ""))

        self.post.comment(badges_str, image=image)
        self.post.comment(self._get_second_comment())

    def _register_badges(self):
        assert self.post.id is not None
        for badge in self.handler.badges:
            badge.register(self.user.id, self.post.id)

    def _get_first_comment(self) -> str:
        badges = self.handler.badges
        badges_len = len(badges)

        if badges_len == 1:
            badge_str = f"🏆 {self.user.name} won one badge:\n{badges[0].fb_reason}"
        else:
            intro = f"🏆 {self.user.name} won {badges_len} badges:\n"
            list_ = "\n".join(badge.fb_reason for badge in badges)
            badge_str = "\n".join((intro, list_))

        req_com = f"Command: {self.request.pretty_title}"

        return "\n\n".join((badge_str, req_com, PATREON))

    def _get_second_comment(self) -> str:
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

    @staticmethod
    def _discord_webhook(content: str, images: List[str] = []):
        wbh = DiscordWebhook(DISCORD_WEBHOOK_TEST, content=content)

        for image in images:
            with open(image, "rb") as f:
                wbh.add_file(file=f.read(), filename=os.path.basename(image))

        wbh.execute()
