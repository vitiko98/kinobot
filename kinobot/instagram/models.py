from datetime import datetime
from datetime import timedelta
from typing import List, Optional

from pydantic import BaseModel


class Label(BaseModel):
    id: int
    verdict: str
    request_id: int
    user_id: str

    class Config:
        orm_mode = True


class Schedule(BaseModel):
    id: int
    request_id: int
    start_time: datetime
    expiration: timedelta

    class Config:
        orm_mode = True


class Ticket(BaseModel):
    id: int
    user_id: int
    used: bool
    added: datetime
    expires_in: timedelta

    class Config:
        orm_mode = True


class User(BaseModel):
    id: str
    name: str
    role: Optional[str] = None
    source: Optional[str] = None
    # requests: List[Request] = []

    class Config:
        orm_mode = True


class Request(BaseModel):
    id: int
    content: str
    user_id: str
    added: datetime
    schedules: List[Schedule] = []
    labels: List[Label] = []
    user: User
    verified: bool = False
    used: bool = False

    class Config:
        orm_mode = True


class Post(BaseModel):
    id: int
    request: Request
    added: datetime
    ig_id: str

    class Config:
        orm_mode = True


class MediaItem(BaseModel):
    id: str
    pretty_title: str
    simple_title: str
    parallel_title: str
    sub_title: Optional[str] = None
    keywords: List[str] = []
    type: str

    class Config:
        orm_mode = True


class RequestData(BaseModel):
    type: str
    comment: str

    class Config:
        orm_mode = True


class FinishedRequest(BaseModel):
    media_items: List[MediaItem]
    request_data: RequestData
    image_uris: List[str]

    def multiple_images(self):
        return len(self.image_uris) > 1
