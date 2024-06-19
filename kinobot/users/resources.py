from fastapi import APIRouter
from fastapi import Depends

from . import models
from . import services

router = APIRouter()


def get_service():
    return


@router.get("/users/{user_id}", response_model=models.User)
async def get_user(
    user_id: int, user_service: services.UserService = Depends(get_service)
):
    return user_service.get_user(user_id)


@router.post("/users", response_model=models.User)
async def create_user(
    name: str, user_service: services.UserService = Depends(get_service)
):
    user = user_service.create_user(name=name)
    return user
