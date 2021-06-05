import logging

from discord import Embed
from discord.ext import commands

import kinobot.exceptions as exceptions

from ..constants import DISCORD_TRACEBACK_WEBHOOK, PERMISSIONS_EMBED, WEBSITE
from ..utils import fmt_exception, send_webhook

logger = logging.getLogger(__name__)


async def handle_error(ctx, error, show_discord_excs=True):
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

    elif isinstance(error, exceptions.KinoException):
        await ctx.send(embed=_exception_embed(error))

    elif isinstance(error, exceptions.KinoUnwantedException):
        await ctx.send(embed=_exception_embed(error))

    elif isinstance(error, commands.CommandError):
        if show_discord_excs:
            await ctx.send(f"Command exception `{name}` raised: {error}")

    else:
        # Afaik, discord.py error handler does not return a traceback
        logger.error(fmt_exception(error))
        send_webhook(DISCORD_TRACEBACK_WEBHOOK, fmt_exception(error))

        await ctx.send(
            f"Unexpected exception raised: {name}. **This is a bug!** Please "
            "reach #support on the official Discord server (run `!server`)."
        )


def _exception_embed(exception):
    title = f"{type(exception).__name__} exception raised!"
    embed = Embed(title=title, description=str(exception))
    embed.add_field(name="Kinobot's documentation", value=f"{WEBSITE}/docs")
    return embed
