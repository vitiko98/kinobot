#!/usr/bin/env python3
from datetime import datetime
from datetime import timedelta
from typing import Optional

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Interval
from sqlalchemy import String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.orm import Session

from . import models
from .models import UserCreate

Base = declarative_base()


class ExternalID(Base):
    __tablename__ = "external_ids"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    external_id = Column(String, unique=True, nullable=False)
    source = Column(String, nullable=False)

    user = relationship("User", back_populates="external_ids")


class MembershipType(Base):
    __tablename__ = "membership_types"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(String)


class Membership(Base):
    __tablename__ = "memberships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type_id = Column(Integer, ForeignKey("membership_types.id"), nullable=False)
    expires_in = Column(Interval)
    added = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="memberships")
    type = relationship("MembershipType", backref="memberships")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    added = Column(DateTime, default=datetime.utcnow)

    external_ids = relationship(
        "ExternalID", back_populates="user", cascade="all, delete"
    )
    memberships = relationship(
        "Membership", back_populates="user", cascade="all, delete"
    )

    def __str__(self):
        return f"<User {self.id}: {self.name}>"


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, user_id: int) -> Optional[models.User]:
        user_ = self._get(user_id)
        if user_:
            return models.User.from_orm(user_)

        return user_

    def create(self, user_create: UserCreate) -> models.User:
        user = User(**user_create.dict())
        self.session.add(user)
        self.session.commit()

        return models.User.from_orm(user)

    def _get(self, user_id: int) -> Optional[User]:
        return self.session.query(User).filter(User.id == user_id).first()

    def update(self, user_id, user_create: UserCreate) -> models.User:
        db_user = self._get(user_id)

        self.session.add(db_user)

        if db_user:
            for field, value in user_create.dict(exclude_unset=True).items():
                setattr(db_user, field, value)

            self.session.commit()
            self.session.refresh(db_user)

        return models.User.from_orm(db_user)

    def delete(self, user_id: int) -> None:
        user = self._get(user_id)
        self.session.delete(user)
        self.session.commit()


class MembershipRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, id: int) -> Optional[models.Membership]:
        item = self._get(id)
        if item:
            return models.Membership.from_orm(item)

        return item

    def _get(self, id):
        return self.db.query(Membership).filter(Membership.id == id).first()

    def create(self, membership_create: models.MembershipCreate) -> models.Membership:
        membership_type = (
            self.db.query(MembershipType)
            .filter(MembershipType.id == membership_create.type_id)
            .first()
        )
        if membership_type is None:
            raise Exception

        membership = Membership(
            type=membership_type,
            user_id=membership_create.user_id,
            expires_in=membership_create.expires_in,
        )
        self.db.add(membership)
        self.db.commit()
        self.db.refresh(membership)
        return models.Membership.from_orm(membership)

    def delete(self, id: int) -> None:
        membership = self._get(id)
        self.db.delete(membership)
        self.db.commit()


class MembershipTypeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, id: int) -> models.MembershipType:
        item = self._get(id)
        if item:
            return models.MembershipType.from_orm(item)

        return item

    def _get(self, id) -> Optional[MembershipType]:
        return self.db.query(MembershipType).filter(MembershipType.id == id).first()

    def create(self, create: models.MembershipTypeCreate) -> models.MembershipType:
        membership_type = MembershipType(**create.dict())
        self.db.add(membership_type)
        self.db.commit()
        self.db.refresh(membership_type)
        return models.MembershipType.from_orm(membership_type)

    def delete(self, id: int) -> None:
        membership_type = self._get(id)
        self.db.delete(membership_type)
        self.db.commit()
