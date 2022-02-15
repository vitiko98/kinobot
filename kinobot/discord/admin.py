#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

# Discord bot for admin tasks.

import asyncio
import logging

import pysubs2
from discord.ext import commands

from ..badge import Punished
from ..db import Execute
from ..exceptions import InvalidRequest
from ..jobs import register_media
from ..media import Episode, Movie
from ..metadata import Category
from ..request import get_cls
from ..user import User
from ..utils import is_episode
from .chamber import Chamber
from .common import handle_error, get_req_id_from_ctx

logging.getLogger("discord").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

bot = commands.Bot(command_prefix="!")


def _get_cls_from_ctx(ctx):
    return get_cls(get_req_id_from_ctx(ctx))


@bot.command(name="verify", help="Verify a request by ID.")
@commands.has_any_role("botmin", "verifier")
async def verify(ctx: commands.Context, id_: str):
    req = _get_cls_from_ctx(ctx).from_db_id(id_)
    req.verify()
    await ctx.send(f"Verified: {req.pretty_title}")


@bot.command(name="delete", help="Mark as used a request by ID.")
@commands.has_any_role("botmin", "verifier")
async def delete(ctx: commands.Context, id_: str):
    req = _get_cls_from_ctx(ctx).from_db_id(id_)
    req.mark_as_used()
    await ctx.send(f"Marked as used: {req.pretty_title}")


@commands.has_any_role("botmin", "verifier")
@bot.command(name="chamber", help="Enter the verification chamber.")
async def chamber(ctx: commands.Context):
    chamber = Chamber(bot, ctx)
    await chamber.start()


@bot.command(name="count", help="Show the count of verified requests.")
async def count(ctx: commands.Context):
    req_cls = _get_cls_from_ctx(ctx)
    await ctx.send(
        f"Verified requests: {Execute().queued_requets(table=req_cls.table)}"
    )


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
@bot.command(name="media", help="Register media")
async def media(ctx: commands.Context):
    await ctx.send("Registering media")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, register_media)
    await ctx.send("Ok")


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


@bot.command(name="punish", help="Punish an user by ID.")
@commands.has_any_role("botmin", "verifier")
async def punish(ctx: commands.Context, id_: str):
    user = User.from_id(id_)
    pbadge = Punished()
    pbadge.register(user.id, ctx.message.id)
    user.purge()
    await ctx.send(f"User successfully purged and punished: {user.name}.")


@bot.command(name="getid", help="Get an user ID by search query.")
@commands.has_any_role("botmin", "verifier")
async def getid(ctx: commands.Context, *args):
    user = User.from_query(" ".join(args))
    await ctx.send(f"{user.name} ID: {user.id}")


@bot.event
async def on_command_error(ctx: commands.Context, error):
    await handle_error(ctx, error)


def _check_botmin(message):
    return str(message.author.top_role) == "botmin"


def run(token: str, prefix: str = "!"):
    bot.command_prefix = prefix

    bot.run(token)
