#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

from typing import Optional

import click

from .constants import DISCORD_ADMIN_TOKEN, DISCORD_PUBLIC_TOKEN
from .discord.admin import run as arun
from .discord.public import run as prun


@click.command()
@click.option("--prefix", default="!", help="Command prefix.")
@click.option("--token", help="Server token.")
def admin(prefix: str, token: Optional[str] = None):
    " Run the admin tasks Discord bot. "
    arun(token or DISCORD_ADMIN_TOKEN, prefix)


@click.command()
@click.option("--prefix", default="!", help="Command prefix.")
@click.option("--token", help="Server token.")
def public(prefix: str, token: Optional[str] = None):
    " Run the public Discord bot. "
    prun(token or DISCORD_PUBLIC_TOKEN, prefix)
