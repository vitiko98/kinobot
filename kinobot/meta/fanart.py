import json
import logging

import pydantic
import requests

logger = logging.getLogger(__name__)


FANART_BASE = "http://webservice.fanart.tv/v3"


class LogoModel(pydantic.BaseModel):
    id: int
    lang: str
    likes: int
    url: str
    tmdb_id: int


class TVLogoModel(pydantic.BaseModel):
    id: int
    lang: str
    likes: int
    url: str
    tvdb_id: int


class FanartClient:
    def __init__(self, api_key, session=None) -> None:
        self._api_key = api_key
        self._session = session or requests.Session()

    def get_movie_logos(self, tmdb_id):
        r = requests.get(
            f"{FANART_BASE}/movies/{tmdb_id}",
            params={"api_key": self._api_key},
            timeout=10,
        )
        r.raise_for_status()

        result = json.loads(r.content)

        logos = []
        for key in ("hdmovielogo", "movielogo"):
            if key not in result:
                continue

            logos.extend(
                LogoModel(**item, tmdb_id=tmdb_id) for item in (result[key] or [])
            )

        logos.sort(key=lambda x: x.likes, reverse=True)

        return logos

    def get_tv_logos(self, tvdb_id):
        r = requests.get(
            f"{FANART_BASE}/tv/{tvdb_id}",
            params={"api_key": self._api_key},
            timeout=10,
        )
        r.raise_for_status()

        result = json.loads(r.content)

        logos = []
        for key in ("hdtvlogo", "tvlogo"):
            if key not in result:
                continue

            logos.extend(
                TVLogoModel(**item, tvdb_id=tvdb_id) for item in (result[key] or [])
            )

        logos.sort(key=lambda x: x.likes, reverse=True)

        return logos
