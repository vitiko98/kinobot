import logging

import aiohttp
from discord import DiscordException, Embed, Forbidden
from discord.ext import commands

import kinobot.exceptions as exceptions

from ..constants import PERMISSIONS_EMBED, WEBSITE
from ..utils import handle_general_exception

logger = logging.getLogger(__name__)


async def handle_error(ctx, error):
    if hasattr(error, "original"):
        error = error.original

    name = type(error).__name__

    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(
            f"Please cool down; try again in `{error.retry_after:.2f}"
            " seconds`. Thanks for understanding."
        )

    elif isinstance(error, exceptions.LimitExceeded):
        await ctx.send(embed=PERMISSIONS_EMBED)

    elif isinstance(error, exceptions.NothingFound):
        if not str(error).strip():
            await ctx.send("Nothing found.")
        else:
            await ctx.send(embed=_exception_embed(error))

    elif isinstance(error, exceptions.KinoUnwantedException):
        handle_general_exception(error)
        await ctx.send(
            f"Unexpected exception raised: {name}. **This is a bug!** Please "
            "reach #support on the official Discord server (run `!server`)."
        )

    elif isinstance(error, exceptions.KinoException):
        await ctx.send(embed=_exception_embed(error))

    # TODO: make this more elegant
    elif isinstance(error, (commands.CommandError, Forbidden)):
        if isinstance(error, Forbidden):
            await ctx.send("Without permissions to perform this.")
        elif not isinstance(error, commands.CommandNotFound):
            await ctx.send(f"Command exception `{name}` raised: {error}")

    elif isinstance(error, aiohttp.ClientError):
        await ctx.send("Please try again. The server was suffering overload.")

    else:
        handle_general_exception(error)
        await ctx.send(
            f"Unexpected exception raised: {name}. **This is a bug!** Please "
            "reach #support on the official Discord server (run `!server`)."
        )


def _exception_embed(exception):
    title = f"{type(exception).__name__} exception raised!"
    embed = Embed(title=title, description=str(exception))
    embed.add_field(name="Kinobot's documentation", value=f"{WEBSITE}/docs")
    return embed
