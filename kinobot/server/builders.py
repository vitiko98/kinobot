import logging

from . import config
from . import services

logger = logging.getLogger(__name__)


class BuildError(Exception):
    pass


def test_transporter_config():
    config_ = config.load()
    name = config_.services.default_image_transporter.name
    try:
        services.transporters[name]
    except KeyError:
        raise BuildError(f"'{name}' is not a registered transporter")


def get_transporter():
    config_ = config.load().services.default_image_transporter

    return services.transporters[config_.name](config_.config)


def run_uvicorn(**kwargs):
    from fastapi import FastAPI
    import uvicorn

    from . import exception_handlers
    from . import router

    app = FastAPI(exception_handlers=exception_handlers.registry)  # type: ignore
    app.include_router(router.router)

    config_ = config.load().rest.dict()
    config_.update(kwargs)

    logger.info("Uvicorn config: %s", config_)

    uvicorn.run(app, **config_)
