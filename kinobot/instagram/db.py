from datetime import datetime
from datetime import timedelta
from typing import Optional

from sqlalchemy import and_
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import create_engine
from sqlalchemy import DateTime
from sqlalchemy import desc
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Interval
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

from . import models
from .config import settings

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, nullable=False)
    name = Column(String, nullable=False)
    added = Column(DateTime, default=datetime.utcnow)


class IGPost(Base):
    __tablename__ = "ig_posts"
    id = Column(Integer, primary_key=True)
    ig_id = Column(String, unique=True)
    request_id = Column(Integer, ForeignKey("ig_requests.id"))
    request = relationship("IGRequest", back_populates="posts")
    added = Column(DateTime, default=datetime.utcnow)


class IGTicket(Base):
    __tablename__ = "ig_tickets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Text, ForeignKey("users.id"))
    user = relationship("User")
    added = Column(DateTime, default=datetime.utcnow)
    used = Column(Boolean, default=False)
    expires_in = Column(Interval, default=timedelta(weeks=8))


class IGRequest(Base):
    __tablename__ = "ig_requests"
    id = Column(Integer, primary_key=True)
    content = Column(Text)
    posts = relationship("IGPost", back_populates="request")
    user_id = Column(Text, ForeignKey("users.id"))
    user = relationship("User")  # , back_populates="requests")
    added = Column(DateTime, default=datetime.utcnow)
    schedules = relationship("Schedule", back_populates="request")
    labels = relationship("Label", back_populates="request")
    used = Column(Boolean, default=False)
    verified = Column(Boolean, default=False)


class IGUsedTicket(Base):
    __tablename__ = "ig_used_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey("ig_requests.id"))
    ticket_id = Column(Integer, ForeignKey("ig_tickets.id"))
    added = Column(DateTime, default=datetime.utcnow)
    used = Column(Boolean, default=False)


class Label(Base):
    __tablename__ = "ig_labels"
    id = Column(Integer, primary_key=True, autoincrement=True)
    verdict = Column(String)
    request_id = Column(Integer, ForeignKey("ig_requests.id"))
    request = relationship("IGRequest", back_populates="labels")
    user_id = Column(Text, ForeignKey("users.id"))


class Schedule(Base):
    __tablename__ = "ig_schedules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    comment = Column(String, nullable=True)
    start_time = Column(DateTime)
    expiration = Column(Interval)
    request_id = Column(Integer, ForeignKey("ig_requests.id"))
    request = relationship("IGRequest", back_populates="schedules")


class PostRepository:
    def __init__(self, session):
        self.session = session

    def get_all(self):
        return self.session.query(IGPost).all()

    def get_last(self):
        item = self.session.query(IGPost).order_by(desc(IGPost.added)).first()
        if item is None:
            return item

        return models.Post.from_orm(item)

    def get_by_id(self, id):
        return self.session.query(IGPost).filter_by(id=id).first()


class RequestRepository:
    def __init__(self, session):
        self.session = session

    def get_all(self):
        return self.session.query(IGRequest).all()

    def get(self, id):
        item = self.session.query(IGRequest).filter_by(id=id).first()
        if item is None:
            return item

        return models.Request.from_orm(item)

    def get_by_id(self, id):
        return self.session.query(IGRequest).filter_by(id=id).first()

    def get_random_active_request(self):
        item = (
            self.session.query(IGRequest)
            .filter(
                and_(
                    IGRequest.verified == True,
                    IGRequest.used == False,
                )
            )
            .order_by(func.random())
            .first()
        )
        if item is not None:
            return models.Request.from_orm(item)

    def get_active_requests_for_user(self, user_id):
        items = (
            self.session.query(IGRequest)
            .filter(
                and_(
                    IGRequest.verified == True,
                    IGRequest.used == False,
                    IGRequest.user_id == user_id,
                )
            )
            .all()
        ) or []
        return [models.Request.from_orm(req) for req in items]

    def get_all_active_requests(self):
        items = (
            self.session.query(IGRequest)
            .filter(
                and_(
                    IGRequest.verified == True,
                    IGRequest.used == False,
                )
            )
            .all()
        ) or []
        return [models.Request.from_orm(req) for req in items]

    def create(self, content, user_id):
        req = IGRequest(content=content, user_id=user_id)
        self.session.add(req)
        self.session.commit()
        self.session.refresh(req)
        return models.Request.from_orm(req)

    def label(self, request_id, user_id, verdict="verified"):
        label = Label(request_id=request_id, user_id=user_id, verdict=verdict)
        self.session.add(label)
        self.session.commit()
        self.session.refresh(label)

        return models.Label.from_orm(label)

    def verify(self, request_id):
        req = self.get_by_id(request_id)
        req.verified = True
        req.used = False
        self.session.commit()
        self.session.refresh(req)

    def schedule(self, request_id, start_time=None, expiration=timedelta(weeks=1)):
        schedule = Schedule(
            request_id=request_id,
            start_time=start_time or datetime.utcnow(),
            expiration=expiration,
        )
        self.session.add(schedule)
        self.session.commit()
        self.session.refresh(schedule)
        return models.Schedule.from_orm(schedule)

    def quarantine(self, request_id):
        req = self.get_by_id(request_id)
        req.quarantine = True
        req.used = True
        self.session.commit()

    def delete(self, request_id):
        req = self.get_by_id(request_id)
        self.session.delete(req)
        self.session.commit()

    def post(self, ig_id, request_id):
        post = IGPost(ig_id=ig_id, request_id=request_id)
        self.session.add(post)
        self.session.commit()
        self.session.refresh(post)
        return models.Post.from_orm(post)


class UserRepository:
    def __init__(self, db):
        self.db = db

    def create_user(self, id, name) -> models.User:
        db_user = User(id=id, name=name)
        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user)
        return models.User.from_orm(db_user)

    def get_user_by_id(self, user_id: str) -> Optional[models.User]:
        db_user = self.db.query(User).filter(User.id == user_id).first()
        if db_user is None:
            return db_user

        return models.User.from_orm(db_user)

    def add_tickets(self, user_id, count):
        for _ in range(count):
            ticket = IGTicket(user_id=user_id)
            self.db.add(ticket)

        self.db.commit()

    def get_all_tickets(self, user_id):
        result = self.db.query(IGTicket).filter(and_(IGTicket.user_id == user_id)).all()
        return [models.Ticket.from_orm(item) for item in result]

    def get_available_tickets(self, user_id):
        result = (
            self.db.query(IGTicket)
            .filter(and_(IGTicket.user_id == user_id, IGTicket.used == False))
            .all()
        )
        return [models.Ticket.from_orm(item) for item in result]

    def register_ticket(self, ticket_id, request_id):
        ticket = self.db.query(IGTicket).filter_by(id=ticket_id).first()
        ticket.used = True
        self.db.add(ticket)

        used = IGUsedTicket(ticket_id=ticket.id, request_id=request_id)
        self.db.add(used)
        self.db.commit()

    def delete_tickets(self, user_id, count):
        subquery = (
            self.db.query(IGTicket.id)
            .filter(and_(IGTicket.user_id == user_id, IGTicket.used == False))
            .limit(count)
            .subquery()
        )
        self.db.query(IGTicket).filter(IGTicket.id.in_(subquery)).delete(
            synchronize_session=False
        )


def make_repository(repo_cls, db_url=None):
    engine = create_engine(db_url or settings.db_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    return repo_cls(session)
