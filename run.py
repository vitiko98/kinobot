#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

import click

import kinobot

try:
    if "test" == sys.argv[1]:
        kinobot.KINOBASE = kinobot.KINOBASE + ".save"
        kinobot.REQUESTS_DB = kinobot.REQUESTS_DB + ".save"
        kinobot.REQUESTS_JSON = kinobot.REQUESTS_JSON + ".save"
        kinobot.DISCORD_WEBHOOK = kinobot.DISCORD_WEBHOOK_TEST
except IndexError:
    pass


from kinobot.comments import collect
from kinobot.db import update_library
from kinobot.discord_bot import discord_bot
from kinobot.post import publish, testing


@click.group()
def cli():
    pass


cli.add_command(collect)
cli.add_command(discord_bot)
cli.add_command(update_library)
cli.add_command(publish)
cli.add_command(testing)

if __name__ == "__main__":
    sys.exit(cli())
