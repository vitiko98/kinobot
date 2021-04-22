import logging

import kinobot.exceptions as exceptions

from ..constants import PERMISSIONS_EMBED

logger = logging.getLogger(__name__)


async def handle_error(ctx, error):
    og_error = error.original
    name = type(og_error).__name__

    logger.error(error, exc_info=True)

    if isinstance(og_error, exceptions.LimitExceeded):
        await ctx.send(embed=PERMISSIONS_EMBED)

    elif isinstance(og_error, exceptions.NothingFound):
        await ctx.send("Nothing found.")

    elif isinstance(og_error, exceptions.KinoException):
        await ctx.send(f"{name} raised: {og_error}")

    elif isinstance(og_error, exceptions.KinoUnwantedException):
        await ctx.send(f"Unwanted exception {name} raised: {og_error}")

    else:
        await ctx.send(
            f"Unexpected exception raised: {name}. **This is a bug!** Please "
            "ping the admin."
        )
