#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import logging
import os
import shutil
from typing import Optional

import click

from .constants import (DISCORD_ADMIN_TOKEN, DISCORD_PUBLIC_TOKEN,
                        DISCORD_PUBLIC_TOKEN_TEST, KINOBASE)
from .db import Kinobase
from .discord.admin import run as arun
from .discord.public import run as prun
from .jobs import sched
from .register import EpisodeRegister, MediaRegister
from .utils import create_needed_folders, init_rotating_log

logger = logging.getLogger(__name__)


@click.group()
@click.option("--test-db", is_flag=True, help="Use a test database.")
@click.option("--log", help="Rotating log path.", metavar="PATH")
def cli(test_db: bool = False, log: Optional[str] = None):
    "Aesthetically perfectionist bot for cinephiles."
    if log is not None:
        init_rotating_log(log)

    if test_db:
        new_db = KINOBASE + ".save"
        if not os.path.isfile(new_db):
            logger.info("Created test database: %s", new_db)
            shutil.copy(KINOBASE, new_db)

        Kinobase.__database__ = new_db

    logger.warning("Active database: %s", Kinobase.__database__)

    create_needed_folders()


@click.command()
@click.option("--prefix", default="!", help="Command prefix.")
@click.option("--token", help="Server token.")
def admin(prefix: str, token: Optional[str] = None):
    "Run the admin tasks Discord bot."
    arun(token or DISCORD_ADMIN_TOKEN, prefix)


@click.command()
@click.option("--prefix", default="!", help="Command prefix.")
@click.option("--test", is_flag=True, help="Use the test token.")
def public(prefix: str, test: bool = False):
    "Run the public Discord bot."
    token = DISCORD_PUBLIC_TOKEN_TEST if test else DISCORD_PUBLIC_TOKEN
    prun(token, prefix)


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
