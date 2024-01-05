import datetime
import logging
import os
from typing import Optional

from plexapi.server import PlexServer
from pydantic import BaseModel
from pydantic import Field

from kinobot.config import settings
from kinobot.media import EpisodeAlt
from kinobot.media import TVShowAlt

logger = logging.getLogger(__name__)


class PlexTVShow(BaseModel):
    id: int = Field(alias="tmdb")
    name: str = Field(alias="title")
    backdrop_path: Optional[str] = None
    poster_path: Optional[str] = None
    popularity: float = 0
    imdb: Optional[str] = None
    tvdb: Optional[int] = None
    firs_air_date: Optional[str] = None
    last_air_date: Optional[str] = None
    status: str = ""
    overview: str = Field(alias="summary", default="")
    added: datetime.datetime = Field(default_factory=datetime.datetime.now)
    hidden: bool = False

    def save(self):
        tv_show = TVShowAlt(**self.dict())
        tv_show.register()


class PlexEpisode(BaseModel):
    tv_show_id: str
    season: int = Field(alias="parentIndex")
    episode: int = Field(alias="index")
    title: str = ""
    path: str
    id: int = Field(alias="tvdb")
    overview: str = Field(alias="summary", default="")
    runtime: int = 0
    hidden: bool = False
    added: datetime.datetime = Field(default_factory=datetime.datetime.now)

    def to_episode(self):
        return EpisodeAlt(**self.dict())


def _extract_guids(show):
    items = {}
    for guid in show.guids:
        parts = guid.id.split("//")
        if len(parts) == 2:
            items[parts[0].rstrip(":")] = parts[1]

    return items


def _replace_path(path, new, old):
    relative = os.path.relpath(path, old)
    return os.path.join(new, relative)


def _get_path(episode):
    try:
        path = episode.media[0].parts[0].file
        return _replace_path(path, *settings.plex.mappings)
    except Exception as error:
        return None


def _parse_show(show):
    guids = _extract_guids(show)
    if "tmdb" not in guids:
        guids["tmdb"] = guids.get("tvdb", guids.get("imdb")) or show.ratingKey

    return PlexTVShow(**vars(show), **guids)


def _parse_episode(episode, show_):
    episode_guids = _extract_guids(episode)

    if not episode_guids or "tvdb" not in episode_guids:
        episode_guids[
            "tvdb"
        ] = f"{show_.id}{episode.index}{episode.parentIndex}00000000"

    path = _get_path(episode)
    if path:
        ep = PlexEpisode(
            **vars(episode), **episode_guids, tv_show_id=show_.id, path=path
        )
        return ep


def get_episodes():
    server = PlexServer(settings.plex.host, settings.plex.token)

    tv_shows = server.library.section("Anime Series")
    all_shows = tv_shows.all()
    items = {"shows": [], "episodes": []}

    for show in all_shows:
        try:
            show_ = _parse_show(show)
        except Exception as error:
            logger.exception(error)
            continue

        show_.save()
        items["shows"].append(show_)

        for episode in show.episodes():
            try:
                ep = _parse_episode(episode, show_)
                if ep:
                    items["episodes"].append(ep)
            except Exception as error:
                logger.exception(error)

    return items
