#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

# Discord bot for admin tasks.

import asyncio
from asyncio.tasks import sleep
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
from ..utils import is_episode, sync_local_subtitles
from .chamber import Chamber
from .common import get_req_id_from_ctx, handle_error
from .extras.curator import MovieView, RadarrClient

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
@bot.command(name="syncsubs", help="Sync local subtitles")
async def syncsubs(ctx: commands.Context):
    await ctx.send("Syncing local subtitles")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, sync_local_subtitles)
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


def _check_author(author):
    return lambda message: message.author == author


@bot.command(name="addm", help="Add a movie to the database.")
@commands.has_any_role("botmin", "curator")
async def addmovie(ctx: commands.Context, *args):
    query = " ".join(args)
    client = RadarrClient.from_constants()

    loop = asyncio.get_running_loop()

    movies = await loop.run_in_executor(None, client.lookup, query)
    movies = movies[:10]

    movie_views = [MovieView(movie) for movie in movies]

    str_list = "\n".join(
        f"{n}. {m.pretty_title()}" for n, m in enumerate(movie_views, 1)
    )
    await ctx.send(f"Choose the item you want to add:\n\n{str_list}")
    chosen_index = 0

    try:
        msg = await bot.wait_for(
            "message", timeout=120, check=_check_author(ctx.author)
        )
        try:
            chosen_index = int(msg.content.lower().strip()) - 1
            movies[chosen_index]
        except (ValueError, IndexError):
            return await ctx.send("Invalid index! Bye")

    except asyncio.TimeoutError:
        return await ctx.send("Timeout! Bye")

    chosen_movie_view = movie_views[chosen_index]
    if chosen_movie_view.already_added() or chosen_movie_view.to_be_added():
        return await ctx.send("This movie is already added/queued")

    await ctx.send(embed=chosen_movie_view.embed())
    await ctx.send("Are you sure? (y/n). If you abuse this function, you'll get banned")
    sure = False

    try:
        msg = await bot.wait_for(
            "message", timeout=120, check=_check_author(ctx.author)
        )
        sure = msg.content.lower().strip() == "y"
    except asyncio.TimeoutError:
        return await ctx.send("Timeout! Bye")

    if not sure:
        return await ctx.send("Dumbass (jk)")

    result = await loop.run_in_executor(None, client.add, movies[chosen_index], True)

    pretty_title = f"**{chosen_movie_view.pretty_title()}**"

    await ctx.send(
        f"{pretty_title} added to the queue. Bot will try to add it automatically."
    )

    await asyncio.sleep(10)

    retries = 0
    grabbed_event_sent = False

    while 15 > retries:
        events = await loop.run_in_executor(
            None, client.events_in_history, result["id"]
        )
        for event in events:
            if event == "downloadFolderImported":
                return await ctx.reply(f"{pretty_title} is ready!")

            if event == "grabbed" and not grabbed_event_sent:
                grabbed_event_sent = True
                await ctx.reply(
                    f"Good news: {pretty_title} is being imported. Let's wait..."
                )
            else:
                logger.debug("Unknown event: %s", event)

        retries += 1
        await asyncio.sleep(60)

    if grabbed_event_sent:
        await ctx.reply(
            f"{pretty_title} is taking too much time to import. Botmin will "
            "have a look if the issue persists."
        )
    else:
        await ctx.reply(
            f"Impossible to add {pretty_title} automatically. Botmin will check it manually."
        )


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


def run(token: str, prefix: str):
    bot.command_prefix = prefix

    bot.run(token)
