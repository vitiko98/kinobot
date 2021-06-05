#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

# Discord bot for admin tasks.

import asyncio
import logging

import pysubs2
from discord.ext import commands

from ..db import Execute
from ..exceptions import InvalidRequest
from ..media import Episode, Movie
from ..metadata import Category
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


@bot.command(name="count", help="Show the count of verified requests.")
async def count(ctx: commands.Context):
    await ctx.send(f"Verified requests: {Execute.queued_requets()}")


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


@commands.has_any_role("botmin")
@bot.command(name="sync", help="Sync subtitles from a movie or an episode")
async def sync(ctx: commands.Context, *args):
    query = " ".join(args)
    if is_episode(query):
        item = Episode.from_query(query)
    else:
        item = Movie.from_query(query)

    await ctx.send(f"Syncing: `{item.simple_title}`.")

    item.sync_subtitles()

    await ctx.send("Ok.")


@commands.has_any_role("botmin")
@bot.command(name="fsub", help="Change subtitles timestamp")
async def fsub(ctx: commands.Context, *args):
    time = args[-1].strip()
    try:
        sec, mss = [int(item) for item in time.split(".")]
    except ValueError:
        raise InvalidRequest(f"Invalid timestamps: {time}")

    query = " ".join(args).replace(time, "")
    if is_episode(query):
        item = Episode.from_query(query)
    else:
        item = Movie.from_query(query)

    subs = pysubs2.load(item.subtitle)
    subs.shift(s=sec, ms=mss)

    await ctx.send(f"Shifted `{sec}s:{mss}ms`. Type `reset` to restore it.")

    try:
        msg = await bot.wait_for("message", timeout=60, check=_check_botmin)

        if "reset" in msg.content.lower().strip():
            subs.shift(s=-sec, ms=-mss)
            await ctx.send("Restored.")

    except asyncio.TimeoutError:
        pass

    subs.save(item.subtitle)

    await ctx.send(f"Subtitles updated for `{item.pretty_title}`.")


@commands.has_any_role("botmin")
@bot.command(name="cat", help="Add category to a random untagged movie.")
async def cat(ctx: commands.Context, *args):
    if not args:
        movie = Movie(**Category.random_untagged_movie())
    else:
        movie = Movie.from_query(" ".join(args))

    await ctx.send(f"Tell me the new category for {movie.simple_title}:")

    try:
        msg = await bot.wait_for("message", timeout=60, check=_check_botmin)

        if "pass" not in msg.content.lower().strip():
            category = Category(name=msg.content.strip().title())
            category.register_for_movie(movie.id)
            await ctx.send(embed=movie.embed)
        else:
            await ctx.send("Ignored.")

    except asyncio.TimeoutError:
        await ctx.send("Bye")


@bot.event
async def on_command_error(ctx: commands.Context, error):
    await handle_error(ctx, error)


def _check_botmin(message):
    return str(message.author.top_role) == "botmin"


def run(token: str, prefix: str = "!"):
    bot.command_prefix = prefix

    bot.run(token)
