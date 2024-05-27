from kinobot.constants import KINOBASE
from typing import Tuple
import datetime
import pydantic
import sqlite3


class Oldie(pydantic.BaseModel):
    request_id: str
    comment: str
    added: datetime.datetime
    impressions: int
    engaged_users: int
    shares: int
    type: str

    @property
    def content(self):
        if not self.comment.startswith("!"):
            return f"{self.type} {self.comment}"

        return self.comment

    def __str__(self) -> str:
        return f"content='{self.content}' " + super().__str__()


class Repo:
    def __init__(self, path) -> None:
        self._path = path

    def get(
        self,
        from_: Tuple[str, str],
        to_: Tuple[str, str],
        limit=100,
        random=True,
    ):
        with sqlite3.connect(self._path) as conn:
            items = conn.execute(
                (
                    "SELECT r.id,r.comment,r.added,p.engaged_users,p.impressions,p.shares,r.type FROM requests r JOIN (SELECT * FROM posts WHERE "
                    "added BETWEEN datetime(?,?) AND datetime(?,?) ORDER BY "
                    "engaged_users DESC LIMIT ?) p ON r.id = p.request_id ORDER BY RANDOM();"
                ),
                (
                    *from_,
                    *to_,
                    limit,
                ),
            ).fetchall()

        oldies = []
        for i in items:
            oldies.append(
                Oldie(
                    request_id=i[0],
                    comment=i[1],
                    added=i[2],
                    engaged_users=i[3],
                    impressions=i[4],
                    shares=i[5],
                    type=i[6],
                )
            )

        return oldies

    @classmethod
    def from_constants(cls):
        return cls(KINOBASE)
