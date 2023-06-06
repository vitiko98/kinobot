import asyncio

from kinobot.sources.comics import client as comic_client
from discord import Embed
from discord.ext import commands


async def call_with_typing(ctx, loop, *args):
    result = None
    async with ctx.typing():
        result = await loop.run_in_executor(*args)

    return result


async def explorecomics(bot, ctx: commands.Context, *args):
    query = " ".join(args)
    query = comic_client.ComicQuery.from_str(query)
    client = comic_client.Client.from_config()
    if not query.title:
        return await ctx.send("No title provided")

    loop = asyncio.get_running_loop()

    item = await call_with_typing(ctx, loop, None, client.first_series_matching, query.title)
    if not item:
        return await ctx.send("Comic not found in db.")

    if not item.chapters:
        return await ctx.send("This comic doesn't have any issues")

    rec = f"""The issues shown above are available to request. You may get the page numbers to request
by your own mediums - be it physical copies, e-readers, or digital platforms.

Request example: {item.name} issue X page X !comic [0:0]"""
    issues = ", ".join([chapter.number for chapter in item.chapters])[:1000]
    await ctx.send(f"**Title:** {item.name}\n**Issues:** {issues}\n\n*{rec}*")
