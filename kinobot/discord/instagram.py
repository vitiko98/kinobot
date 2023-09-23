import asyncio
import logging

from discord import Embed
from discord.ext import commands
import requests

from kinobot.instagram import Client as IGCLient
from kinobot.instagram import config
from kinobot.instagram import db
from kinobot.instagram import factory
from kinobot.instagram import services
from kinobot.instagram.events import PostCreated
from kinobot.instagram.models import Request as RequestModel
from kinobot.instagram.models import User as UserModel
from kinobot.request import NothingFound
from kinobot.request import Request

from .utils import ask
from .utils import ask_to_confirm
from .utils import call_with_typing
from .utils import paginated_list

logger = logging.getLogger(__name__)


def _quarantine(pc: PostCreated):
    logger.debug("Running quarantine for %s", pc)
    req = Request.from_db_id(str(pc.request.id))
    req.mark_as_used()


def _other_publishers(pc: PostCreated):
    cfg = config.Config.default_factory()
    pubs = factory.make_post_publishers(cfg.publishers)
    for pub in pubs:
        try:
            pub(pc)
        except Exception as error:
            logger.debug("Error runing %s: %s", pub, error)


def _picker(id=None):
    if id is None:
        try:
            req_ = Request.random_from_queue(verified=True, tag="ig")
        except NothingFound:
            logger.debug("No verified request found")
            return None
    else:
        req_ = Request.from_db_id(id)

    req_.user.load()
    req = RequestModel(
        id=req_.id,  # type: ignore
        content=req_.comment,
        user_id=req_.user.id,
        added=req_.added,
        user=UserModel(id=req_.user.id, name=req_.user.name),
    )
    return req


def make_post(request_id=None):
    cfg = config.Config.default_factory()
    client = IGCLient(**cfg.ig_client)
    handler = services.Handler(**cfg.client)

    def _publishers(pc):
        for pub in (_quarantine, _other_publishers):
            try:
                pub(pc)
            except Exception as error:
                logger.debug("Error running %s: %s", error)

    services.post(
        client,
        lambda: _picker(request_id),
        handler.request,
        event_publisher=_publishers,
    )
