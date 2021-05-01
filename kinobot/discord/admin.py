#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

# Discord bot for admin tasks.

import logging

from discord.ext import commands

from ..media import Episode, Movie
from ..request import Request
from ..utils import is_episode
from .chamber import Chamber
from .common import handle_error

logging.getLogger("discord").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

bot = commands.Bot(command_prefix="!")


@bot.command(name="verify", help="Verify a request by ID.")
@commands.has_any_role("botmin", "verifier")
async def verify(ctx: commands.Context, id_: str):
    req = Request.from_db_id(id_)
    req.verify()
    await ctx.send(f"Verified: {req.pretty_title}")


@bot.command(name="delete", help="Mark as used a request by ID.")
@commands.has_any_role("botmin", "verifier")
async def delete(ctx: commands.Context, id_: str):
    req = Request.from_db_id(id_)
    req.mark_as_used()
    await ctx.send(f"Marked as used: {req.pretty_title}")


@commands.has_any_role("botmin", "verifier")
@bot.command(name="chamber", help="Enter the verification chamber.")
async def chamber(ctx: commands.Context):
    chamber = Chamber(bot, ctx)
    await chamber.start()


@commands.has_any_role("botmin")
@bot.command(name="blacklist", help="Blacklist a movie or an episode")
async def blacklist(ctx: commands.Context, *args):
    query = " ".join(args)
    if is_episode(query):
        item = Episode.from_query(query)
    else:
        item = Movie.from_query(query)

    item.hidden = True
    item.update()
    await ctx.send(f"Blacklisted: {item.simple_title}.")


@bot.event
async def on_command_error(ctx: commands.Context, error):
    await handle_error(ctx, error)


def run(token: str, prefix: str = "!"):
    bot.command_prefix = prefix

    bot.run(token)
