from typing import Dict, List, Optional

import pydantic
import requests

_BASE_URL = "https://animebytes.tv"


class Client:
    def __init__(self, username, passkey, session=None) -> None:
        self._username = username
        self._passkey = passkey

        self._def_params = {"username": self._username, "torrent_pass": self._passkey}

        self._session = session or requests.Session()

    def search(self, searchstr):
        params = {
            "searchstr": searchstr,
            "action": "advanced",
            "type": "anime",
            "sort": "relevance",
            "way": "desc",
            "showhidden": "0",
            "limit": 50,
            "anime[tv_series]": "1",
        }
        r = self._session.get(
            f"{_BASE_URL}/scrape.php", params={**self._def_params, **params}
        )

        r.raise_for_status()

        try:
            groups = r.json()["Groups"]
        except KeyError:
            return []

        items = []
        for g in groups:
            items.append(AnimeSeries(**g))

        return items

    def download(self, url, output):
        response = self._session.get(url)
        response.raise_for_status()
        with open(output, "wb") as file:
            file.write(response.content)

        return output


class EditionData(pydantic.BaseModel):
    title: Optional[str] = pydantic.Field(alias="EditionTitle")


class Torrent(pydantic.BaseModel):
    id: int = pydantic.Field(alias="ID")
    raw_down_multiplier: float = pydantic.Field(alias="RawDownMultiplier")
    edition_data: EditionData = pydantic.Field(alias="EditionData")
    link: str = pydantic.Field(alias="Link")
    size: int = pydantic.Field(alias="Size")
    file_count: int = pydantic.Field(alias="FileCount")
    property_: str = pydantic.Field(alias="Property")

    @property
    def pretty_title(self):
        properties = ", ".join(
            [
                i.strip()
                for i in self.property_.split("|")
                if "Freeleech" not in i and "subs" not in i.lower()
            ]
        )
        return f"{self.edition_data.title or ''} | {properties} | {self.file_count} item(s) | {round(self.size / (1024 ** 3), 2)}GB"


class Links(pydantic.BaseModel):
    anidb: Optional[str] = pydantic.Field(alias="AniDB")
    ann: Optional[str] = pydantic.Field(alias="ANN")


class AnimeSeries(pydantic.BaseModel):
    id: str = pydantic.Field(alias="ID")
    links: Links = pydantic.Field(alias="Links")
    year: str = pydantic.Field(alias="Year")
    series_name: str = pydantic.Field(alias="SeriesName")
    series_id: str = pydantic.Field(alias="SeriesID")
    torrents: List[Torrent] = pydantic.Field(alias="Torrents")

    @property
    def pretty_title(self):
        return f"{self.series_name} ({self.year})"
