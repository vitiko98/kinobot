import logging
from typing import List

from . import Client
from . import config
from . import db
from . import publishers
from . import services

logger = logging.getLogger(__name__)

_mapped_params = {
    "request": db.RequestRepository,
    "user": db.UserRepository,
    "post": db.PostRepository,
}


_func_map = {"make_repository": lambda a, b=None: [db.make_repository(a, b)]}


def _handle_factory(data: dict, publisher_name):
    func_ = _func_map[data["func"]]
    publisher = publishers.publishers[publisher_name]
    args = []

    for arg in data.get("args", []):
        if isinstance(arg, str) and arg.startswith("mapped."):
            args.append(_mapped_params[arg.lstrip("mapped.")])
        else:
            args.append(arg)

    args = func_(*args, **data.get("kwargs", {}))
    return publisher(*args)


def _handle_default(data: dict, publisher_name):
    publisher = publishers.publishers[publisher_name]
    return publisher(*data.get("args", []), **data.get("kwargs", {}))


def make_post_kwargs(config: config.Config):
    handler = services.Handler(**config.client)
    #  req_repo = db.make_repository(db.RequestRepository, config.db_url)
    client = Client(**config.ig_client)

    def _event_publisher(finished):
        pubs = make_post_publishers(config.publishers)
        for pub in pubs:
            logger.debug("Running %s", pub)
            pub(finished)

    return dict(
        client=client,
        # picker=req_repo.get_random_active_request,
        req_handler=handler,
        event_publisher=_event_publisher,
    )


def make_post_publishers(publisher_configs: List[config.Publisher]):
    items = []
    for publisher in publisher_configs:
        logger.debug(publisher)
        if publisher.enabled is False:
            logger.debug("Not enabled: %s", publisher)
            continue

        if publisher.handler not in publishers.publishers:
            logger.debug("Handler not registered: %s", publisher.handler)
            continue

        constructor = publisher.constructor
        if not constructor:
            logger.debug("Invalid constructor: %s", constructor)
            continue

        if "factory" in constructor:
            logger.debug("Mapped factory")
            item = _handle_factory(constructor["factory"], publisher.handler)
        else:
            logger.debug("Default factory")
            item = _handle_default(constructor, publisher.handler)

        logger.debug("Created publisher: %s", item)
        items.append(item)

    return items
