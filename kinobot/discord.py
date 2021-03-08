#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import logging
import os
import re
import sqlite3

import asyncio
import click

from random import randint, shuffle, choice

from discord import File
from discord.ext import commands

import kinobot.db as db

from kinobot.api import handle_request, handle_music_request
from kinobot import DISCORD_TOKEN, KINOLOG_PATH
from kinobot.comments import dissect_comment
from kinobot.music import search_tracks, extract_id_from_url
from kinobot.exceptions import KinoException
from kinobot.utils import kino_log

LOG = os.path.join(KINOLOG_PATH, "discord_admin.log")

REQUEST_RE = re.compile(r"[^[]*\[([^]]*)\]")

BASE = "https://kino.caretas.club"

RANGE_DICT = {"1️⃣": 0, "2️⃣": 1, "3️⃣": 2, "4️⃣": 3, "5️⃣": 4}
GOOD_BAD = ("👍", "💩")
NEXT_EMOJI = "➡️"
EMOJI_STRS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")

bot = commands.Bot(command_prefix="!")


logger = logging.getLogger(__name__)


def _check_botmin(message):
    return str(message.author.top_role) == "botmin"


def _enumerate_requests(requests):
    return "\n".join(
        [
            f"{n}. **{req[0]}** ~ *{req[2]}* - {req[1]}"
            for n, req in enumerate(requests, start=1)
        ]
    )


async def handle_discord_request(ctx, command, args, music=False):
    request = " ".join(args)
    user_disc = ctx.author.id
    username = db.get_name_from_discriminator(user_disc)

    if not username:
        return await ctx.send("You are not registered. Use !register.")

    try:
        request_dict = dissect_comment(f"!{command} {request}", music)
        if not request_dict:
            return await ctx.send("Invalid syntax.")
    except Exception as error:
        return await ctx.send(f"Exception raised: {type(error).__name__}.")

    request_id = str(randint(2000000, 5000000))

    db.insert_request(
        (
            username[0],
            request_dict["comment"],
            request_dict["command"],
            request_dict["title"],
            "|".join(request_dict["content"]),
            request_id,
            1,
        )
    )

    db.verify_request(request_id)

    await ctx.send(f"Added. ID: {request_id}; user: {username[0]}.")


@bot.command(name="req", help="make a regular request")
async def request(ctx, *args):
    await handle_discord_request(ctx, "req", args)


@bot.command(name="parallel", help="make a parallel request")
async def parallel(ctx, *args):
    await handle_discord_request(ctx, "parallel", args)


@bot.command(name="palette", help="make a palette request")
async def palette(ctx, *args):
    await handle_discord_request(ctx, "palette", args)


@bot.command(name="mreq", help="make a music request")
async def mreq(ctx, *args):
    await handle_discord_request(ctx, "req", args, music=True)


@bot.command(name="register", help="register yourself")
async def register(ctx, *args):
    name = " ".join(args).title()
    discriminator = ctx.author.id
    if not name:
        return await ctx.send("Usage: `!register <YOUR NAME>`")

    if not "".join(args).isalpha():
        return await ctx.send("Invalid name.")

    try:
        db.register_discord_user(name, discriminator)
        return await ctx.send(f"You were registered as '{name}'.")
    except sqlite3.IntegrityError:
        try:
            old_name = db.get_name_from_discriminator(discriminator)[0]
            db.update_discord_name(name, discriminator)
            db.update_name_from_requests(old_name, name)
            return await ctx.send(f"Your name was updated: '{name}'.")
        except (TypeError, sqlite3.IntegrityError):
            return await ctx.send("Duplicate name.")


@bot.command(name="pq", help="get priority queue")
async def priority_queue(ctx):
    queue = db.get_priority_queue()
    if queue:
        shuffle(queue)
        await ctx.send("\n".join(queue[:15]))
    else:
        await ctx.send("Nothing found.")


@bot.command(name="sr", help="search requests")
async def search_request_(ctx, *args):
    query = " ".join(args)

    if query.endswith("!1"):
        requests = db.search_requests(query.replace("!1", ""))

        if requests:
            final = []
            for request in requests:
                content = REQUEST_RE.findall(request[0])
                if len(content) == 1:
                    final.append(request)

            requests = final[:5]
            return await ctx.send(_enumerate_requests(requests))
    else:
        requests = db.search_requests(query)[:5]
        if requests:
            return await ctx.send(_enumerate_requests(requests))

    await ctx.send("Nothing found.")


@bot.command(name="music", help="add a music video to the database", usage="URL QUERY")
async def music(ctx, *args):
    url = args[0]
    query = " ".join(args[1:])

    video_id = extract_id_from_url(url)
    if not video_id:
        return await ctx.reply("Video ID not found.")

    results = list(search_tracks(query))
    if not results:
        return await ctx.reply("Track not found.")

    tracks = [f"{n}. {item['complete']}" for n, item in enumerate(results, 1)]

    message = await ctx.reply(
        "Select the track to save. Make sure that tags don't look like "
        "shit!\n\n" + "\n".join(tracks)
    )

    [await message.add_reaction(emoji) for emoji in EMOJI_STRS[: len(results)]]

    def check_react(reaction_, user_):
        return user_ == ctx.author

    try:
        reaction, user = await bot.wait_for(
            "reaction_add", timeout=20, check=check_react
        )
    except asyncio.TimeoutError:
        return await ctx.reply("Timeout. Choose one next time, dumbass.")

    index = RANGE_DICT[str(reaction)]
    selected = results[index]

    try:
        if str(ctx.author.top_role) == "botmin":
            await ctx.reply("Tell me the category.")
            msg = await bot.wait_for("message", timeout=30, check=_check_botmin)
            category = msg.content
        else:
            category = "Unknown"

        db.insert_music_video(video_id, selected["artist"], selected["title"], category)
        message_ = await ctx.reply(
            f"Music added to the database: {tracks[index]} with '{category}' "
            "category. React :poop: to delete it."
        )

        await message_.add_reaction(GOOD_BAD[1])

        reaction, user = await bot.wait_for(
            "reaction_add", timeout=20, check=check_react
        )

        if str(reaction) == GOOD_BAD[1]:
            db.delete_music_video(video_id)
            await ctx.reply("Deleted.")

    except sqlite3.IntegrityError:
        await ctx.reply("Already added.")


@bot.command(name="sm", help="search for music videos in the db", usage="QUERY")
async def search_m(ctx, *args):
    query = " ".join(args)
    results = db.search_db_tracks(query)
    if not results:
        return await ctx.reply("Nothing found.")

    tracks = [
        f"{n}. {item[1]} - {item[2]} ({item[3]})" for n, item in enumerate(results)
    ]
    await ctx.reply("Results:\n\n" + "\n".join(tracks))

    if str(ctx.author.top_role) != "botmin":
        return

    await ctx.reply("`{INDEXES,...}:TEXT`")

    msg = await bot.wait_for("message", timeout=45, check=_check_botmin)
    commands_ = str(msg.content).split()

    changed = []
    for command_ in commands_:
        try:
            numbers, text = command_.split(":")
        except ValueError:
            continue

        for number in numbers.split(","):
            tmp_index = int(number)

            if "delete" in text:
                db.delete_music_video(results[tmp_index][0])
                changed.append(f"Deleted: {tracks[tmp_index]}.")
            else:
                db.update_music_category(results[tmp_index][0], text)
                changed.append(f"{text} for {results[tmp_index][2]}.")

    if changed:
        await ctx.reply("Changed:\n\n" + "\n".join(changed))


@commands.has_any_role("botmin", "verifier")
@bot.command(name="chamber", help="enter the verification chamber")
async def chamber(ctx, arg=""):
    type_ = "movies" if arg not in ("movies", "episodes", "music") else arg

    handler = handle_music_request if type_ == "music" else handle_request

    await ctx.send(f"Starting request handler for '{type_}' type...")

    request_list = db.get_requests(type_, priority_only=False, verified=False)

    if not request_list:
        return await ctx.reply("Nothing found for '{type_}' type.")

    def check_react(reaction_, user_):
        return user_ == ctx.author

    while True:
        try:
            request_dict = choice(db.get_requests(type_, False, False))
        except IndexError:
            return await ctx.reply("Nothing found for '{type_}' type.")

        request_dict["on_demand"] = True

        try:
            async with ctx.typing():
                result = handler(request_dict, False)

            await ctx.send(request_dict["comment"])

            for image in result["images"]:
                with open(image, "rb") as bot_image:
                    message = await ctx.send(file=File(bot_image))

            [await message.add_reaction(emoji) for emoji in GOOD_BAD]
            await message.add_reaction("🧊")

            try:
                await ctx.send(
                    "You got 45 seconds to react to the last image. React "
                    "with the ice cube to deal with the request later."
                )

                reaction, user = await bot.wait_for(
                    "reaction_add", timeout=45, check=check_react
                )

                if str(reaction) == str(GOOD_BAD[0]):
                    await ctx.send(db.verify_request(request_dict["id"]))

                if str(reaction) == str(GOOD_BAD[1]):
                    await ctx.send(db.remove_request(request_dict["id"]))

            except asyncio.TimeoutError:
                return await ctx.send("Timeout. Exiting...")

        except KinoException as error:
            await ctx.send(f"KinoException with request {request_dict['id']}: {error}.")
            db.remove_request(request_dict["id"])
            continue

        except Exception as error:
            logger.error(error, exc_info=True)
            await ctx.send(
                f"Unexpected {type(error).__name__} exception raised: "
                f"{error}. This needs to get fixed!"
            )

        verify_len = len(db.get_requests(type_, True))
        message = await ctx.send(
            "Continue in the chamber? Kinobot already got "
            f"{verify_len} verified requests for '{type_}'."
        )
        [await message.add_reaction(emoji) for emoji in GOOD_BAD]

        try:
            reaction, user = await bot.wait_for(
                "reaction_add", timeout=15, check=check_react
            )

            if str(reaction) == str(GOOD_BAD[0]):
                continue

            return await ctx.send("Bye.")

        except asyncio.TimeoutError:
            return await ctx.send("Timeout. Exiting...")


@bot.command(name="delete", help="delete a request by ID")
@commands.has_any_role("botmin", "verifier")
async def delete(ctx, arg):
    await ctx.send(db.remove_request(arg.strip()))


@bot.command(name="verify", help="verify a request by ID")
@commands.has_any_role("botmin", "verifier")
async def verify(ctx, arg):
    await ctx.send(db.verify_request(arg.strip()))


@bot.command(name="block", help="block an user by name")
@commands.has_any_role("botmin", "verifier")
async def block(ctx, *args):
    user = " ".join(args)
    db.block_user(user.strip())
    db.purge_user_requests(user.strip())
    await ctx.send("Ok.")


@bot.command(name="sql", help="run a sql command on Kinobot's DB (admin-only)")
@commands.has_permissions(administrator=True)
async def sql(ctx, *args):
    command = " ".join(args)
    try:
        db.execute_sql_command(command)
        message = f"Command OK: {command}."
    except sqlite3.Error as sql_exc:
        message = f"Error: {sql_exc}."

    await ctx.send(message)


@click.command("discord")
def discord_bot():
    " Run discord Bot. "
    kino_log(LOG)

    db.create_discord_db()
    db.create_music_db()

    bot.run(DISCORD_TOKEN)
