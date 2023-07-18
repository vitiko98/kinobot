import logging

from . import config
from . import services
from fastapi import FastAPI

from . import exception_handlers
from . import router

logger = logging.getLogger(__name__)


class BuildError(Exception):
    pass


def get_transporter(config):
    config_ = config.services.default_image_transporter

    return services.transporters[config_.name](config_.config)


def get_app(config, **kwargs):
    app = FastAPI(exception_handlers=exception_handlers.registry)  # type: ignore
    app.include_router(router.router)

    rest_config = config.rest.dict()

    rest_config.update(kwargs)

    app.dependency_overrides[router.get_api_key] = lambda: rest_config["api_key"]
    app.dependency_overrides[router.get_transporter] = lambda: get_transporter(config)
    return app
