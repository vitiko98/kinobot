import asyncio
import logging

from discord.ext import commands
from discord import Embed
import requests

from kinobot.sources.sports import registry

from .utils import ask
from .utils import ask_to_confirm
from .utils import call_with_typing
from .utils import paginated_list

logger = logging.getLogger(__name__)


async def add(bot, ctx: commands.Context, video_url):
    video_url = video_url.strip()

    await ctx.send(
        "Give me the title of the match. It's usually TEAM 1 vs. TEAM 2, except for certain sports.\n"
        "Examples: `Liverpool vs. Everton`; `New York Knicks vs. Brooklyn Nets`; `Montreal Canadiens vs. Toronto Maple Leafs`; `Usain Bolt - Men's 100 metres`\n"
        "Please check your grammar."
    )
    title = await ask(bot, ctx)

    await ctx.send(
        "Now the tournament of the event. It's usually a title followed by its season identifier or its year.\n"
        "Examples: `Premier League 2021-22; NBA 2021-22; NHL 2021-22; 2008 Beijing Summer Olympics`"
    )
    tournament = await ask(bot, ctx)

    confirmed = await ask_to_confirm(
        bot, ctx, f"{title} - {tournament}\n\nThis will be the title. Are you sure?"
    )
    if not confirmed:
        return await ctx.send("Bye.")

    repo = registry.Repository.from_db_url()
    result = repo.create(tournament, title, video_url)
    await ctx.send(f"Added: {result.pretty_title}")


def _get_embed(items):
    embed = Embed(title="Matches found")

    str_list = "\n".join(f"{n}. {m.markdown_url}" for n, m in enumerate(items, 1))

    embed.add_field(name="Titles", value=str_list)
    return embed


async def explore(bot, ctx: commands.Context, *args):
    loop = asyncio.get_running_loop()

    query = " ".join(args)
    repo = registry.Repository.from_db_url()
    results = repo.partial_search(query)

    if not results:
        return await ctx.send("Nothing found")

    results = results[:20]

    await ctx.send(embed=_get_embed(results))
