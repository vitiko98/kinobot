#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
from kinobot.db import update_library, generate_static_poster_collages
from kinobot.discord import discord_bot
from kinobot.post import publish, testing
from kinobot.twitter import start_twitter_loop


@click.group()
def cli():
    pass


for command in (
    collect,
    discord_bot,
    update_library,
    generate_static_poster_collages,
    publish,
    testing,
    start_twitter_loop,
):
    cli.add_command(command)


if __name__ == "__main__":
    sys.exit(cli())
