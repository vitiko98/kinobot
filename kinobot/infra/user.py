from typing import Optional

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from . import maker
from . import translate_exc
from ._orm import Request
from ._orm import User
from ._orm import user_collab


class UserModel(BaseModel):
    id: str
    name: str
    role: Optional[str]  # Legacy trash
    source: Optional[str]  # Legacy trash

    class Config:
        orm_mode = True


class UserCollabService:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def get_collaborators(self, request_id: str) -> list:
        with self._session_factory() as session:
            users = (
                session.query(User)
                .join(user_collab)
                .join(Request)
                .filter(Request.id == request_id)
                .all()
            )
            return [UserModel.from_orm(user) for user in users]

    @translate_exc(
        IntegrityError,
        checker=lambda e: "unique constraint" in str(e).lower(),
        output_maker=lambda _: "Duplicate item",
    )
    def create_collaboration(self, user_id: str, request_id: str) -> None:
        with self._session_factory() as session:
            collaboration = user_collab.insert().values(
                user_id=user_id, request_id=request_id
            )
            session.execute(collaboration)
            session.commit()

    def delete_collaboration(self, user_id: str, request_id: str) -> None:
        with self._session_factory() as session:
            session.query(user_collab).filter_by(
                user_id=user_id, request_id=request_id
            ).delete()
            session.commit()

    @classmethod
    def default(cls):
        return cls(maker())
