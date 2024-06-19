#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import os
import shutil
from typing import Optional

import click


from .config import config
from .db import Kinobase
from .discord.admin import run as arun
from .discord.public import run as prun
from .jobs import fb_sched
from .jobs import sched
from .register import EpisodeRegister
from .register import MediaRegister
from .utils import create_needed_folders
from .utils import init_log
from .utils import init_rotating_log
from .infra import _migration

logger = logging.getLogger(__name__)


def run_alembic():
    _migration.run_alembic()


_BOTS = {
    "foreign": config.discord.token_public_foreign,
    "public": config.discord.token_public,
    "test": config.discord.token_patreon_test,
}


@click.group()
@click.option("--test-db", is_flag=True, help="Use a test database.")
@click.option("--log", help="Rotating log path.", metavar="PATH")
@click.option("--log-level", help="Logging level.", metavar="INFO")
def cli(
    test_db: bool = False, log: Optional[str] = None, log_level: Optional[str] = None
):
    "Aesthetically perfectionist bot for cinephiles."
    init_log(level=log_level or "INFO")
    run_alembic()

    if log is not None:
        init_rotating_log(log, level=log_level or "INFO")

    if test_db:
        new_db = config.db + ".save"
        if not os.path.isfile(new_db):
            logger.info("Created test database: %s", new_db)
            shutil.copy(config.db, new_db)

        Kinobase.__database__ = new_db

    logger.warning("Active database: %s", Kinobase.__database__)

    create_needed_folders()


@click.command()
def migration():
    run_alembic()


@click.command()
@click.option("--prefix", default="!", help="Command prefix.")
@click.option("--token", help="Server token.")
def admin(prefix: str, token: Optional[str] = None):
    "Run the admin tasks Discord bot."
    arun(token or config.discord.token_admin, prefix)


@click.command()
@click.option("--prefix", default=None, help="Bot's prefix")
@click.option("--name", default="test", help="Bot's name (public, test, foreign)")
def public(name: str, prefix: Optional[str] = None):
    "Run the public Discord bot."
    token = _BOTS[name]
    logger.debug("Starting %s bot", name)
    prun(token, token == config.discord.token_public_foreign, custom_prefix=prefix)


@click.command()
@click.option("--all-media", is_flag=True, help="Add media without subtitles.")
def register(all_media: bool = False):
    "Register media to the database."
    for media in (MediaRegister, EpisodeRegister):
        handler = media(only_w_subtitles=not all_media)
        handler.load_new_and_deleted()
        handler.handle()


@click.command()
def bot():
    "Run the Facebook bot."
    sched.start()


@click.command()
def fb():
    "Run the Facebook loop."
    fb_sched.start()


@click.command()
@click.option("--config", default=None, help="Server yaml config")
def server(config: Optional[str] = None):
    import uvicorn

    from .server import builders

    config_ = builders.config.load(config)
    rest_config = config_.rest
    app = builders.get_app(config_)

    uvicorn.run(app, port=rest_config.port, host=rest_config.host)
