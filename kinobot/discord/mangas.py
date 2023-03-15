import asyncio
import logging
from typing import List

from discord import Embed
from discord.ext import commands

from kinobot.sources.manga import registry
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


async def _ask_msg(bot, ctx):
    try:
        msg = await bot.wait_for(
            "message", timeout=120, check=_check_author(ctx.author)
        )
        return msg.content.strip()
    except asyncio.TimeoutError:
        return await ctx.send("Timeout! Bye")


def _get_mangas_embed(items: List[registry.Manga]) -> Embed:
    embed = Embed(title="Mangas found")

    str_list = "\n".join(f"{n}. {m.markdown_url}" for n, m in enumerate(items, 1))

    embed.add_field(name="Titles", value=str_list)
    return embed


async def exploremangas(bot, ctx: commands.Context, *args):
    query = " ".join(args)
    repo = registry.Repository.from_constants()
    items = repo.simple_search(query)
    if not items:
        return await ctx.send("Nothing found.")

    await ctx.send(embed=_get_mangas_embed(items))


async def addmanga(bot, ctx: commands.Context, *args):
    query = " ".join(args)

    user = User.from_discord(ctx.author)
    user.load()

    loop = asyncio.get_running_loop()

    client = registry.Client()

    items = await call_with_typing(ctx, loop, None, client.search, query)

    if not items:
        return await ctx.send("Nothing found")

    msg = "Choose the item you want to add ('n' to ignore). Avoid titles with special tags or spam or you'll get banned!"
    await _pretty_title_list(ctx, items, msg=msg)

    chosen_index = await _interactive_index(bot, ctx, items)
    if chosen_index is None:
        return None

    chosen_item = items[chosen_index]  # type: registry.Manga

    await ctx.send(f"**{chosen_item.pretty_title()}**\n\nAdd item? (y/n)")

    if not await _interactive_y_n(bot, ctx):
        return None

    await ctx.send("Fetching chapters...")
    await call_with_typing(ctx, loop, None, chosen_item.fetch_chapters, client)
    repo = registry.Repository.from_constants()

    try:
        repo.add_manga(chosen_item, True)
    except registry.AlreadyAdded:
        pass

    await ctx.send(f"Manga registered with {chosen_item.id} ID")
