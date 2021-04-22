#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

# Discord bot for admin tasks.

import asyncio
import logging

import kinobot.exceptions as exceptions

from discord import File
from discord.ext import commands

from ..request import Request
from ..user import User
from .common import handle_error

_GOOD_BAD_NEUTRAL = ("👍", "💩", "🧊")

logging.getLogger("discord").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

bot = commands.Bot(command_prefix="!")


def _format_exc(error: Exception) -> str:
    return f"{type(error).__name__} raised: {error}"


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
    def check_react(reaction, user):
        assert reaction
        return user == ctx.author

    # TODO: Prettify this loop
    while True:
        req = Request.random_from_queue(verified=False)
        try:
            async with ctx.typing():
                handler = req.get_handler()
                images = handler.get()

        except exceptions.KinoException as error:
            await ctx.send(_format_exc(error))
            req.mark_as_used()
            continue

        except exceptions.KinoUnwantedException as error:
            await ctx.send(_format_exc(error))
            continue

        except Exception as error:
            await ctx.send(f"**Fatal!!!** {_format_exc(error)}")
            continue

        user = User(id=req.user_id)
        user.load(register=True)

        message = None
        await ctx.send(f"Author: {user.name}; content: {req.pretty_title}")

        for image in images:
            logger.info("Sending image: %s", image)
            message = await ctx.send(file=File(image))

        [await message.add_reaction(emoji) for emoji in _GOOD_BAD_NEUTRAL]
        try:
            await ctx.send(
                "You got 45 seconds to react to the last image. React "
                "with the ice cube to deal with the request later."
            )

            reaction, user = await bot.wait_for(
                "reaction_add", timeout=45, check=check_react
            )
            assert user

            if str(reaction) == str(_GOOD_BAD_NEUTRAL[0]):
                req.verify()
                await ctx.send("Verified")

            elif str(reaction) == str(_GOOD_BAD_NEUTRAL[1]):
                req.mark_as_used()
                await ctx.send("Marked as used")
            else:
                await ctx.send("Ignored")

        except asyncio.TimeoutError:
            await ctx.send("Timeout. Exiting...")
            break

        message = await ctx.send("Continue in the chamber?")
        [await message.add_reaction(emoji) for emoji in _GOOD_BAD_NEUTRAL[:2]]

        try:
            reaction, user = await bot.wait_for(
                "reaction_add", timeout=15, check=check_react
            )

            if str(reaction) == str(_GOOD_BAD_NEUTRAL[0]):
                continue

            await ctx.send("Bye.")
            break

        except asyncio.TimeoutError:
            return await ctx.send("Timeout. Exiting...")


@bot.event
async def on_command_error(ctx: commands.Context, error):
    await handle_error(ctx, error)


def run(token: str, prefix: str = "!"):
    bot.command_prefix = prefix

    bot.run(token)
