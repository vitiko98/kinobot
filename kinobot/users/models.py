import datetime
from typing import List

from pydantic import BaseModel
from pydantic import validator


class MembershipType(BaseModel):
    id: int
    name: str
    description: str

    class Config:
        orm_mode = True


class Membership(BaseModel):
    id: int
    expires_in: datetime.timedelta
    added: datetime.datetime
    type: MembershipType

    class Config:
        orm_mode = True


class ExternalID(BaseModel):
    id: int
    external_id: str
    source: str

    class Config:
        orm_mode = True


class User(BaseModel):
    id: int
    name: str
    added: datetime.datetime
    memberships: List[Membership] = []
    external_ids: List[ExternalID] = []

    class Config:
        orm_mode = True


class UserCreate(BaseModel):
    name: str

    @validator("name")
    def _validate_name(cls, v: str):
        assert v.isalnum(), "must be alphanumeric"
        return v


class MembershipCreate(BaseModel):
    expires_in: datetime.timedelta
    user_id: int
    type_id: int


class MembershipTypeCreate(BaseModel):
    name: str
    description = ""
