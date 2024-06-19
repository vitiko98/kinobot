import asyncio
import logging
import os
import tempfile
from typing import List

from discord.ext import commands

from kinobot.config import settings
from kinobot.misc import ab
from kinobot.misc import anime

from . import utils
from .extras.curator_user import AnimeCurator

logger = logging.getLogger(__name__)


def _update_anime():
    anime.handle_downloaded()
    anime.scan_subs()


async def update(bot, ctx):
    loop = asyncio.get_event_loop()
    await utils.call_with_typing(ctx, loop, _update_anime)
    await ctx.send("Done.")


async def add(bot, ctx: commands.Context, *args):
    with AnimeCurator(ctx.author.id, settings.db) as curator:
        size_left = curator.size_left()

    query = " ".join(args)
    client = ab.Client(settings.anime.username, settings.anime.passkey)
    loop = asyncio.get_event_loop()
    items = await utils.call_with_typing(
        ctx, loop, client.search, query
    )  # type: List[ab.AnimeSeries]
    if not items:
        await ctx.send("Nothing found.")
        return

    item = await utils.paginated_list(
        bot, ctx, "Choose the group", items, lambda i: i.pretty_title
    )
    if item is None:
        return await ctx.send("Bye.")

    series_name = item.series_name

    filtered = list(filter(lambda p: "m2ts" not in p.property_.lower(), item.torrents))

    item = await utils.paginated_list(
        bot,
        ctx,
        "Now choose what item to import",
        filtered,
        lambda i: i.pretty_title,
    )
    if not item:
        return await ctx.send("Bye.")

    if item.size > size_left:
        return await ctx.send("Not enough GBs to perform this.")

    if not await utils.ask_to_confirm(bot, ctx):
        return await ctx.send("Bye.")

    downloaded_t = os.path.join(tempfile.gettempdir(), f"{item.id}.torrent")

    await utils.call_with_typing(ctx, loop, client.download, item.link, downloaded_t)
    del_client = anime.Client.from_config()
    torrent_id = await utils.call_with_typing(
        ctx, loop, del_client.add_torrent_file, downloaded_t
    )
    anime.register_torrent(torrent_id, series_name)

    with AnimeCurator(ctx.author.id, settings.db) as curator:
        curator.register_addition(item.size)

    await ctx.send("Added to queue. Let's wait.")
