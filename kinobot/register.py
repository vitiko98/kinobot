#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import json
import logging
import sqlite3
import time
from typing import List, Optional

import requests
import tmdbsimple as tmdb
from facepy import GraphAPI

from kinobot.cache import MEDIA_LIST_TIME, region
from kinobot.media import Episode, Movie, TVShow

from .badge import InteractionBadge
from .constants import (
    DISCORD_ANNOUNCER_WEBHOOK,
    FACEBOOK_TOKEN,
    RADARR_TOKEN,
    RADARR_URL,
    SONARR_TOKEN,
    SONARR_URL,
    TMDB_KEY,
)
from .db import Kinobase
from .exceptions import InvalidRequest, KinoException, SubtitlesNotFound
from .post import Post
from .request import Request
from .user import User
from .utils import send_webhook

tmdb.API_KEY = TMDB_KEY

logger = logging.getLogger(__name__)

_FB_REQ_TYPES = (
    "!req",
    "!parallel",
    "!palette",
)


class FacebookRegister(Kinobase):
    " Class for Facebook metadata scans. "

    def __init__(self, page_limit: int = 20, page_token: Optional[str] = None):
        self.page_limit = page_limit
        self.page_token = page_token or FACEBOOK_TOKEN
        self._api = GraphAPI(self.page_token)
        self._comments: List[dict] = []
        self._posts: List[Post] = []
        self.__collected = False

    def requests(self):
        " Register requests. "
        logger.info("Registering requests")
        self._collect()
        for request in self._comments:
            self._register_request(request)

    def ratings(self):
        " Register ratings. "
        logger.info("Registering ratings")
        self._collect()
        for comment in self._comments:
            try:
                self._rate_movie(comment)
            except KinoException as error:
                logger.error(error)

    def badges(self):
        " Register new interaction badges if found. "
        self._collect_posts()

        logger.debug("Collected posts: %d", len(self._posts))
        for post in self._posts:
            try:
                self._collect_badges(post)
            except KinoException as error:
                logger.error("KinoException collection badges: %s", error)

    @staticmethod
    def _collect_badges(post: Post):
        assert post.id is not None
        reacts, shares = post.get_reacts_and_shares()
        comments = post.get_comments()
        views, clicks = post.get_engagements()

        types = {
            "reacts": reacts,
            "comments": comments,
            "views": views,
            "clicks": clicks,
            "shares": shares,
        }
        to_notify, user = [], None

        for badge in InteractionBadge.__subclasses__():
            bdg = badge()
            int_value = types[badge.type]
            logger.debug("Checking %d value for %s type", int_value, badge.type)
            if bdg.check(int_value):
                try:
                    bdg.register(post.user_id, post.id)
                except sqlite3.IntegrityError:
                    logger.debug("Already registered")
                    continue

                if user is None:
                    user = User.from_id(post.user_id)

                to_notify.append(f"**{bdg.name.title()}**")

        if to_notify and user is not None:
            badge_strs = ", ".join(to_notify)
            msg = f"`{user.name}` just won: {badge_strs}.\n<{post.facebook_url}>"
            send_webhook(DISCORD_ANNOUNCER_WEBHOOK, msg)

    def _collect(self):
        " Collect 'requests' from Kinobot's last # posts. "
        if self.__collected:
            logger.info("Already collected")
            return

        kinobot = self._api  # Temporary

        logger.info("About to scan %d posts", self.page_limit)

        for post in kinobot.get("me/posts", limit=self.page_limit).get("data", []):  # type: ignore
            comments = kinobot.get(str(post.get("id")) + "/comments")
            for comment in comments.get("data", []):  # type: ignore
                self._comments.append(comment)

        self.__collected = True

    def _collect_posts(self):
        # Four hours ago, for reach killer badges
        until = str(round(time.time() - 14400))

        posts = self._api.get(
            "me/posts",
            limit=self.page_limit,
            fields="attachments{target{id}}",
            until=until,
        )
        assert isinstance(posts, dict)

        logger.debug("About to scan %d posts", len(posts["data"]))
        for post in posts["data"]:
            atts = post.get("attachments", {}).get("data")

            if atts is None:
                continue

            if len(atts) == 1:
                self._posts.append(
                    Post(id=atts[0]["target"]["id"], parent_id=post["id"])
                )
            else:
                self._posts.append(Post(**post))

            logger.debug("Collected posts: %s", len(self._posts))

    def _collect_generator(self, limit: int = 3):
        # Four hours ago, for reach killer badges
        until = str(round(time.time() - 14400))
        count = 1

        for post in self._api.get(
            "me/posts",
            limit=99,
            fields="attachments{target{id}}",
            until=until,
            page=True,
        ):
            assert isinstance(post, dict)
            for item in post["data"]:
                yield item

            count += 1

            if count > limit:
                break

    @staticmethod
    def _register_request(comment: dict):
        msg = comment.get("message", "n/a")

        for type_ in _FB_REQ_TYPES:

            if not msg.startswith(type_):
                continue

            request = Request.from_fb(comment)
            request.type = type_  # Workaround

            request.register()
            break

    @staticmethod
    def _rate_movie(comment: dict):
        """
        :param comment:
        :type comment: dict
        :raises:
            exceptions.InvalidRequest
            exceptions.MovieNotFound
        """
        msg = comment.get("message", "n/a").strip()
        if msg.startswith("!rate"):
            clean = msg.replace("!rate", "").strip().split()  # ["xx", "rate"]

            rating = clean[-1].split("/")[0]

            try:
                rating = float(rating)
            except ValueError:
                raise InvalidRequest(f"Invalid rating: {rating}") from None

            user = User.from_fb(**comment.get("from", {}))
            user.register()

            movie = Movie.from_query(" ".join(clean))

            user.rate_media(movie, rating)


class MediaRegister(Kinobase):
    type = "movies"

    def __init__(self, only_w_subtitles: bool = False):
        self.only_w_subtitles = only_w_subtitles
        self.external_items = []
        self.local_items = []
        self.new_items = []
        self.deleted_items = []
        self.modified_items = []

    def load_new_and_deleted(self):
        self._load_local()
        self._load_external()

        for external in self.external_items:
            if not any(str(item.id) == str(external.id) for item in self.local_items):
                logger.info("Appending missing item: %s", external)
                self.new_items.append(external)

        for local in self.local_items:
            if not any(str(item.id) == str(local.id) for item in self.external_items):
                logger.info("Appending deleted item: %s", local)
                self.deleted_items.append(local)

        # Modified paths
        for local in self.local_items:
            if not any(item.path == local.path for item in self.external_items):
                try:
                    local.path = next(
                        item.path
                        for item in self.external_items
                        if str(local.id) == str(item.id)
                    )
                except StopIteration:
                    continue
                logger.info("Appending item with new path: %s", local.path)
                self.modified_items.append(local)

    def handle(self):
        self._handle_deleted()
        self._handle_new()
        self._handle_modified()

    def _handle_new(self):
        if not self.new_items:
            logger.info("No new items to add")
        else:
            for new in self.new_items:
                try:
                    assert new.subtitle
                except SubtitlesNotFound:
                    if self.only_w_subtitles:
                        logger.debug("Item %s has no subtitles", new)
                        continue
                new.load_meta()
                new.register()
                if self.type == "movies":
                    send_webhook(DISCORD_ANNOUNCER_WEBHOOK, new.webhook_embed)

    def _handle_deleted(self):
        if not self.deleted_items:
            logger.info("No items to delete")
        else:
            for deleted in self.deleted_items:
                deleted.hidden = True
                deleted.update()

    def _handle_modified(self):
        if not self.modified_items:
            logger.info("No items to modify")
        else:
            for item in self.modified_items:
                item.update()
                if self.type == "movies":
                    send_webhook(DISCORD_ANNOUNCER_WEBHOOK, item.webhook_embed)

    def _load_local(self):
        class_ = Movie if self.type == "movies" else Episode
        items = self._db_command_to_dict(f"select * from {self.type} where hidden=0")
        self.local_items = [class_(**item) for item in items]  # type: ignore

    def _load_external(self):
        self.external_items = [
            Movie.from_radarr(item) for item in _get_radarr_list("cache")
        ]


class EpisodeRegister(MediaRegister):
    type = "episodes"

    def _load_external(self):
        self.external_items = [
            Episode.from_register_dict(item) for item in _get_episodes("cache")
        ]


# Cached functions


@region.cache_on_arguments(expiration_time=MEDIA_LIST_TIME)
def _get_episodes(cache_str: str) -> List[dict]:
    assert cache_str is not None

    session = requests.Session()

    response = session.get(f"{SONARR_URL}/api/series?apiKey={SONARR_TOKEN}")

    response.raise_for_status()

    series = response.json()

    episode_list = []
    for serie in series:
        if not serie.get("sizeOnDisk", 0):
            continue

        found_ = _get_tmdb_imdb_find(serie["imdbId"])

        tmdb_serie = _get_tmdb_tv_show(found_[0]["id"])

        tv_show = TVShow(imdb=serie["imdbId"], tvdb=serie["tvdbId"], **tmdb_serie)
        tv_show.register()

        tv_show_id = tmdb_serie["id"]

        episodes_r = session.get(
            f"{SONARR_URL}/api/episode",
            params={"apiKey": SONARR_TOKEN, "seriesId": serie.get("id")},
        )

        episodes_r.raise_for_status()

        episodes = [item for item in episodes_r.json() if item["hasFile"]]

        season_ns = [
            season["seasonNumber"]
            for season in serie["seasons"]
            if season["statistics"]["sizeOnDisk"]
        ]

        episode_list += _gen_episodes(season_ns, tv_show_id, episodes)

    return episode_list


def _gen_episodes(season_ns: List[int], tmdb_id: int, radarr_eps: List[dict]):
    for season in season_ns:
        tmdb_season = _get_tmdb_season(tmdb_id, season)

        for episode in tmdb_season["episodes"]:
            try:
                episode["path"] = next(
                    item["episodeFile"]["path"]
                    for item in radarr_eps
                    if item["episodeNumber"] == episode["episode_number"]
                    and season == item["seasonNumber"]
                )
                episode["tv_show_id"] = tmdb_id
                yield episode
            except StopIteration:
                pass


@region.cache_on_arguments(expiration_time=MEDIA_LIST_TIME)
def _get_radarr_list(cache_str: str) -> List[dict]:
    assert cache_str is not None

    response = requests.get(f"{RADARR_URL}/api/v3/movie?apiKey={RADARR_TOKEN}")

    response.raise_for_status()

    return [i for i in json.loads(response.content) if i.get("hasFile")]


@region.cache_on_arguments()
def _get_tmdb_imdb_find(imdb_id):
    find_ = tmdb.find.Find(id=imdb_id)
    results = find_.info(external_source="imdb_id")["tv_results"]
    return results


@region.cache_on_arguments()
def _get_tmdb_tv_show(show_id) -> dict:
    tmdb_show = tmdb.TV(show_id)
    return tmdb_show.info()


@region.cache_on_arguments()
def _get_tmdb_season(serie_id, season_number) -> dict:
    tmdb_season = tmdb.TV_Seasons(serie_id, season_number)
    return tmdb_season.info()
