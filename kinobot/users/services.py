from . import models
from .db import UserRepository


class UserNotFound(Exception):
    pass


class UserService:
    def __init__(self, user_repository: UserRepository):
        self._repo = user_repository

    def get_user(self, user_id: int) -> models.User:
        user = self._repo.get(user_id)
        if user is None:
            raise UserNotFound(user_id)

        return user

    def create_user(self, name: str) -> models.User:
        user_create = models.UserCreate(name=name)
        return self._repo.create(user_create)

    def update_user(self, user_id: int, **data) -> models.User:
        user_create = models.UserCreate(**data)
        return self._repo.update(user_id, user_create)

    def delete_user(self, user_id: int) -> None:
        self._repo.delete(user_id)
