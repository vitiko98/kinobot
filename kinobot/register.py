#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import json
import logging
import os
import time
from typing import List, Optional

from facepy import GraphAPI
import requests
import tmdbsimple as tmdb
import yaml

from kinobot.cache import MEDIA_LIST_TIME
from kinobot.cache import region
from kinobot.media import Episode
from kinobot.media import Movie
from kinobot.media import TVShow

from .constants import DISCORD_ANNOUNCER_WEBHOOK
from .constants import FACEBOOK_TOKEN
from .constants import FACEBOOK_TOKEN_ES
from .constants import FACEBOOK_TOKEN_MAIN
from .constants import FACEBOOK_TOKEN_PT
from .constants import SONARR_ROOT_DIR
from .constants import SONARR_TOKEN
from .constants import SONARR_URL
from .constants import TMDB_KEY
from .constants import TV_SHOWS_DIR
from .constants import YAML_CONFIG
from .db import Kinobase
from .exceptions import InvalidRequest
from .exceptions import KinoException
from .exceptions import NothingFound
from .exceptions import SubtitlesNotFound
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
    "!swap",
)


_token_map = {
    "en": FACEBOOK_TOKEN,
    "es": FACEBOOK_TOKEN_ES,
    "pt": FACEBOOK_TOKEN_PT,
    "main": FACEBOOK_TOKEN_MAIN,
}


class FacebookRegister(Kinobase):
    "Class for Facebook metadata scans."

    def __init__(self, page_limit: int = 20, identifier="en"):
        self.page_limit = page_limit

        try:
            self.page_token = _token_map[identifier]
        except IndexError:
            raise ValueError(f"Token not found for identifier: {identifier}")

        self.identifier = identifier

        logger.debug("Identifier: %s", self.identifier)

        self._api = GraphAPI(self.page_token)
        self._comments: List[dict] = []
        self._posts: List[Post] = []
        self.__collected = False

    def requests(self):
        "Register requests."
        logger.info("Registering requests")
        self._collect()
        for request in self._comments:
            self._register_request(request)

    def ratings(self):
        "Register ratings."
        logger.info("Registering ratings")
        self._collect()
        for comment in self._comments:
            try:
                self._rate_movie(comment)
            except KinoException as error:
                logger.error(error)

    def _collect(self):
        "Collect 'requests' from Kinobot's last # posts."
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
            limit=99,
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
        until = str(round(time.time() - 18000))
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

    def _register_request(self, comment: dict):
        msg = comment.get("message", "n/a")

        for type_ in _FB_REQ_TYPES:

            if not msg.startswith(type_):
                continue

            request = Request.from_fb(comment, self.identifier)
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
                logger.debug("Appending missing item: %s", external)
                self.new_items.append(external)

        for local in self.local_items:
            if not any(str(item.id) == str(local.id) for item in self.external_items):
                logger.debug("Appending deleted item: %s", local)
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
                logger.debug("Appending item with new path: %s", local.path)
                self.modified_items.append(local)

    def handle(self):
        self._handle_deleted()
        self._handle_new()
        self._handle_modified()

    def _handle_new(self):
        if not self.new_items:
            logger.info("No new items to add")
        else:
            logger.info("Items to add: %d", len(self.new_items))
            for new in self.new_items:
                try:
                    assert new.subtitle
                except FileNotFoundError as error:
                    logger.error("File not found: %s", error)
                    continue
                except SubtitlesNotFound:
                    pass
                    # if self.only_w_subtitles:
                    #    logger.debug("Item %s has no subtitles", new)
                    #    continue

                try:
                    new.load_meta()
                except requests.HTTPError as error:
                    logger.error(error, exc_info=True)
                    continue

                new.register()
                if self.type == "movies":
                    send_webhook(DISCORD_ANNOUNCER_WEBHOOK, new.webhook_embed)

            if self.type == "episodes":
                self._mini_notify(self.new_items, "added")

    def _handle_deleted(self):
        if not self.deleted_items:
            logger.info("No items to delete")
        else:
            logger.info("Items to delete: %d", len(self.deleted_items))
            if len(self.deleted_items) > 30:
                logger.info(
                    "Dangerous deleted count: %s. Not deleting anything.",
                    len(self.deleted_items),
                )
            else:
                for deleted in self.deleted_items:
                    deleted.hidden = True
                    deleted.update()

    #            self._mini_notify(self.deleted_items, "deleted")

    def _handle_modified(self):
        if not self.modified_items:
            logger.info("No items to modify")
        else:
            logger.info("Items to modify: %d", len(self.modified_items))
            for item in self.modified_items:
                item.update()

            self._mini_notify(self.modified_items, "updated")

    @staticmethod
    def _mini_notify(items, action="deleted"):
        titles = []
        for i in items:
            try:
                titles.append(i.season_title)
            except:
                titles.append(i.title)

        if len(items) < 20:
            strs = ", ".join(list(dict.fromkeys([f"**{item}**" for item in titles])))
            msg = f"The following items were **{action}**: {strs}"
        else:
            msg = f"**{len(titles)}** items were **{action}**"

        send_webhook(DISCORD_ANNOUNCER_WEBHOOK, msg)

    def _load_local(self):
        class_ = Movie if self.type == "movies" else Episode
        items = self._db_command_to_dict(f"select * from {self.type} where hidden=0")
        self.local_items = [class_(**item) for item in items]  # type: ignore
        logger.debug("Loaded local items: %s", len(self.local_items))

    def _load_external(self):
        self.external_items = [Movie.from_radarr(item) for item in _get_radarr_list()]
        logger.debug("Loaded external items: %s", len(self.external_items))


class EpisodeRegister(MediaRegister):
    type = "episodes"

    def _load_external(self):
        self.external_items = [
            Episode.from_register_dict(item) for item in _get_episodes("cache")
        ]


def _get_episodes(cache_str: str) -> List[dict]:
    assert cache_str is not None

    session = requests.Session()

    response = session.get(f"{SONARR_URL}/api/v3/series?apiKey={SONARR_TOKEN}")

    response.raise_for_status()

    series = response.json()

    episode_list = []

    for serie in series:
        if not serie.get("statistics", {}).get("sizeOnDisk", 0):
            continue

        found_ = _get_tmdb_imdb_find(
            imdb_id=serie.get("imdbId"), tvdb_id=serie.get("tvdbId")
        )
        if not found_:
            logger.info("%s not found with tmdb", serie)
            continue

        tmdb_serie = _get_tmdb_tv_show(found_[0]["id"])

        tv_show = TVShow(
            imdb=serie.get("imdbId", str(serie["tvdbId"])),
            tvdb=serie["tvdbId"],
            **tmdb_serie,
        )
        tv_show.register()

        tv_show_id = tmdb_serie["id"]

        episodes_r = session.get(
            f"{SONARR_URL}/api/v3/episode",
            params={"apiKey": SONARR_TOKEN, "seriesId": serie.get("id")},
        )
        episode_file_r = session.get(
            f"{SONARR_URL}/api/v3/episodeFile",
            params={"apiKey": SONARR_TOKEN, "seriesId": serie.get("id")},
        )

        episodes_r.raise_for_status()
        episode_file_r.raise_for_status()

        episodes = [item for item in episodes_r.json() if item.get("hasFile")]

        season_ns = [
            season["seasonNumber"]
            for season in serie["seasons"]
            if season["statistics"]["sizeOnDisk"]
        ]

        try:
            episode_list += _gen_episodes(
                season_ns, tv_show_id, episodes, episode_file_r.json()
            )
        except requests.exceptions.HTTPError:
            logger.info("Anime fallback for TV Show: %s", tv_show_id)

            episode_list += _gen_episodes_anime_fallback(tv_show_id, episodes)

    return episode_list


def _merge_episode_response(eps, episode_file):
    for ep in eps:
        if not ep.get("episodeFileId"):
            continue

        try:
            ep_file = [
                item for item in episode_file if item["id"] == ep["episodeFileId"]
            ][0]
        except IndexError:
            continue

        ep["episodeFile"] = ep_file


def _gen_episodes(
    season_ns: List[int], tmdb_id: int, sonarr_eps: List[dict], episode_file: List[dict]
):
    _merge_episode_response(sonarr_eps, episode_file)

    for season in season_ns:
        tmdb_season = _get_tmdb_season(tmdb_id, season)

        for episode in tmdb_season["episodes"]:
            try:
                episode["path"] = next(
                    _replace_path(
                        item["episodeFile"]["path"], TV_SHOWS_DIR, SONARR_ROOT_DIR
                    )
                    for item in sonarr_eps
                    if item["episodeNumber"] == episode["episode_number"]
                    and season == item["seasonNumber"]
                )
                episode["tv_show_id"] = tmdb_id
                yield episode
            except (IndexError, KeyError) as error:
                logger.error(error, exc_info=True)
            except StopIteration:
                pass


def _gen_episodes_anime_fallback(tmdb_id: int, radarr_eps: List[dict]):
    tmdb_season = _get_tmdb_season(tmdb_id, 1)

    if len(radarr_eps) != len(tmdb_season["episodes"]):
        raise NothingFound

    for radarr_episode, tmdb_episode in zip(radarr_eps, tmdb_season["episodes"]):
        episode = tmdb_episode.copy()
        try:
            episode["path"] = _replace_path(
                radarr_episode["episodeFile"]["path"], TV_SHOWS_DIR, SONARR_ROOT_DIR
            )
        except KeyError:
            continue
        else:
            episode["tv_show_id"] = tmdb_id
            yield episode


def _get_radar_list_from_config(config: dict):
    response = requests.get(
        f"{config['url']}/api/v3/movie", params={"apiKey": config["token"]}
    )

    response.raise_for_status()

    items = []
    for i in json.loads(response.content):
        if not i.get("hasFile"):
            continue

        i["movieFile"]["path"] = _replace_path(
            i["movieFile"]["path"], config["movies_dir"], config["radarr_root_dir"]
        )
        items.append(i)

    logger.debug("%d items found", len(items))

    return items


def _get_config(path: str, key: Optional[str] = None) -> dict:
    "raises: TypeError, KeyError"
    with open(path, "r") as f:
        data = yaml.safe_load(f)

    if key is not None:
        return data[key]

    return data


def _get_radarr_list(yaml_config=None) -> List[dict]:
    yaml_config = yaml_config or YAML_CONFIG

    if not yaml_config:
        raise NothingFound

    radarr_configs = _get_config(yaml_config, "radarr")
    items = []
    for config in radarr_configs:
        items.extend(_get_radar_list_from_config(config))

    return items


@region.cache_on_arguments()
def _get_tmdb_imdb_find(imdb_id, tvdb_id):
    if imdb_id is not None:
        id = imdb_id
        external_source = "imdb_id"
    elif tvdb_id is not None:
        id = tvdb_id
        external_source = "tvdbId"
    else:
        return []

    find_ = tmdb.find.Find(id=id)
    results = find_.info(external_source=external_source)["tv_results"]
    return results


@region.cache_on_arguments()
def _get_tmdb_tv_show(show_id) -> dict:
    tmdb_show = tmdb.TV(show_id)
    return tmdb_show.info()


@region.cache_on_arguments()
def _get_tmdb_season(serie_id, season_number) -> dict:
    tmdb_season = tmdb.TV_Seasons(serie_id, season_number)
    return tmdb_season.info()


def _replace_path(path, new, old):
    relative = os.path.relpath(path, old)
    return os.path.join(new, relative)
