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
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    comment = Column(Text, nullable=False)
    type = Column(String, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    verified = Column(Boolean, default=False, nullable=False)
    music = Column(Boolean, default=False, nullable=False)
    added = Column(DateTime, default=lambda: datetime.date.today(), nullable=False)
    language = Column(String, default="en", nullable=False)
    data = Column(JSON, nullable=True, default=dict)

    user = relationship("User", lazy=False)


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


class Post(Base):
    __tablename__ = "posts"

    id = Column(String, primary_key=True, nullable=False)
    added = Column(DateTime, server_default="CURRENT_TIMESTAMP", nullable=False)
    request_id = Column(String, ForeignKey("requests.id"))
    shares = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    other_clicks = Column(Integer, default=0)
    photo_view = Column(Integer, default=0)
    engaged_users = Column(Integer, default=0)
    haha = Column(Integer, default=0)
    like = Column(Integer, default=0)
    love = Column(Integer, default=0)
    sad = Column(Integer, default=0)
    angry = Column(Integer, default=0)
    wow = Column(Integer, default=0)
    care = Column(Integer, default=0)
    last_scan = Column(DateTime, server_default="CURRENT_TIMESTAMP")
    request: Mapped["Request"] = relationship()


class UserMoneyBonus(Base):
    __tablename__ = "user_money_bonus"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str]
    amount: Mapped[int]
    post_id: Mapped[str]
    added = Column(DateTime, default=lambda: datetime.date.today(), nullable=False)


#    __table_args__ = (UniqueConstraint("user_id", "post_id", name="umbp_constraint"),)


class UserPayout(Base):
    __tablename__ = "user_payout"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str]
    amount: Mapped[int]
    added = Column(DateTime, default=lambda: datetime.date.today(), nullable=False)


class _CuratorKey:
    __tablename__ = "curator_keys"

    user_id = Column(String, primary_key=True)
    size = Column(Integer, default=0)
    added = Column(DateTime, default=datetime.datetime.now())
    note = Column(Text, default="")
    days_expires_in = Column(Integer, default=90)
