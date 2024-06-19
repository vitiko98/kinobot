import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer
from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base

# Define the database model
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    name = Column(Text, nullable=False)
    role = Column(String, default="Unknown")
    source = Column(String, default="Unknown")


class Request(Base):
    __tablename__ = "requests"
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    comment = Column(Text, nullable=False)
    type = Column(String, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    verified = Column(Boolean, default=False, nullable=False)
    music = Column(Boolean, default=False, nullable=False)
    added = Column(Date, default=lambda: datetime.date.today(), nullable=False)
    language = Column(String, default="en", nullable=False)


user_collab = Table(
    "user_collab",
    Base.metadata,
    Column("user_id", String, ForeignKey("users.id")),
    Column("request_id", String, ForeignKey("requests.id")),
    UniqueConstraint("user_id", "request_id", name="uq_user_collab"),
)


class PostComplete(Base):
    __tablename__ = "post_complete"

    id = Column(String, primary_key=True)
    request_id = Column(String, ForeignKey("requests.id"))
    insights = Column(JSON, default=dict)
    page = Column(String)
    added = Column(DateTime, default=lambda: datetime.datetime.now(), nullable=False)


class CuratorKey(Base):
    __tablename__ = "curator_keys"

    user_id = Column(String, primary_key=True)
    size = Column(Integer, default=0)
    added = Column(DateTime, default=datetime.datetime.now())
    note = Column(Text, default="")
    days_expires_in = Column(Integer, default=90)
