import asyncio
import logging

from discord.ext import commands

from kinobot.sources.music import registry
from kinobot.user import User

logger = logging.getLogger(__name__)


async def call_with_typing(ctx, loop, *args):
    result = None
    async with ctx.typing():
        result = await loop.run_in_executor(*args)

    return result


def _check_author(author):
    return lambda message: message.author == author


async def _interactive_index(bot, ctx, items):
    chosen_index = 0

    try:
        msg = await bot.wait_for(
            "message", timeout=120, check=_check_author(ctx.author)
        )
        try:
            chosen_index = int(msg.content.lower().strip()) - 1
            items[chosen_index]
        except (ValueError, IndexError):
            await ctx.send("Invalid index! Bye")
            return None

    except asyncio.TimeoutError:
        await ctx.send("Timeout! Bye")
        return None

    return chosen_index


async def _pretty_title_list(
    ctx, items, append=None, msg="Choose the item you want to add ('n' to ignore):"
):
    str_list = "\n".join(f"{n}. {m.pretty_title()}" for n, m in enumerate(items, 1))
    msg = f"{msg}\n\n{str_list}"

    if append is not None:
        msg = f"{msg}\n\n{append}"

    await ctx.send(msg)


async def _interactive_y_n(bot, ctx):
    try:
        msg = await bot.wait_for(
            "message", timeout=120, check=_check_author(ctx.author)
        )
        return msg.content.lower().strip() == "y"
    except asyncio.TimeoutError:
        return await ctx.send("Timeout! Bye")


async def exploresongs(bot, ctx: commands.Context, *args):
    query = " ".join(args)
    repo = registry.Repository.from_constants()
    items = repo.simple_search(query)
    if not items:
        return await ctx.send("Nothing found.")

    await _pretty_title_list(ctx, items, msg="")


async def addsong(bot, ctx: commands.Context, video_url, *args):
    video_url = video_url.strip()
    query = " ".join(args)

    user = User.from_discord(ctx.author)
    user.load()

    loop = asyncio.get_running_loop()

    client = registry.Client.from_constants()

    items = await call_with_typing(ctx, loop, None, client.search_track, query)
    await _pretty_title_list(ctx, items)

    chosen_index = await _interactive_index(bot, ctx, items)
    if chosen_index is None:
        return None

    chosen_item = items[chosen_index]

    await ctx.send(f"**{chosen_item.pretty_title()}**\n\nAdd item? (y/n)")

    if not await _interactive_y_n(bot, ctx):
        return None

    new_track = registry.DbTrack(
        artist=chosen_item.artist, name=chosen_item.name, uri=video_url
    )

    repo = registry.Repository.from_constants()
    id_ = repo.add(new_track)
    await ctx.send(f"Added item with {id_} ID")
