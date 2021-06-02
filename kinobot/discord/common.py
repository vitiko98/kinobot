import logging

from discord.ext import commands

import kinobot.exceptions as exceptions

from ..constants import DISCORD_TRACEBACK_WEBHOOK, PERMISSIONS_EMBED
from ..utils import fmt_exception, send_webhook

logger = logging.getLogger(__name__)


async def handle_error(ctx, error):
    if hasattr(error, "original"):
        error = error.original

    name = type(error).__name__

    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Please cool down; try again in {error.retry_after:.2f} secs.")

    elif isinstance(error, exceptions.LimitExceeded):
        await ctx.send(embed=PERMISSIONS_EMBED)

    elif isinstance(error, exceptions.NothingFound):
        if not str(error).strip():
            await ctx.send("Nothing found.")
        else:
            await ctx.send(f"{name} raised: {error}")

    elif isinstance(error, exceptions.KinoException):
        await ctx.send(f"{name} raised: {error}")

    elif isinstance(error, exceptions.KinoUnwantedException):
        await ctx.send(f"Unwanted exception {name} raised: {error}")

    else:
        # Afaik, discord.py error handler does not return a traceback
        logger.error(fmt_exception(error))
        send_webhook(DISCORD_TRACEBACK_WEBHOOK, fmt_exception(error))

        await ctx.send(
            f"Unexpected exception raised: {name}. **This is a bug!** Please "
            "ping the admin on the official Discord server."
        )
