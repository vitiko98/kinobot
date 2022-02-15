#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

# Discord bot for the official Kinobot server.

import asyncio
import logging
from operator import attrgetter
from typing import Optional

from discord import Embed, Member
from discord.ext import commands
from tabulate import tabulate

import kinobot.exceptions as exceptions

from ..badge import Badge
from ..constants import API_HELP_EMBED, DISCORD_BOT_INVITE, DISCORD_INVITE
from ..media import Movie
from ..request import ClassicRequest, PaletteRequest, ParallelRequest, SwapRequest
from ..search import (
    CategorySearch,
    CountrySearch,
    GenreSearch,
    MediaFuzzySearch,
    PersonSearch,
    QuoteSearch,
    RequestSearch,
    SongSearch,
)
from ..top import TopMovies, TopUsers
from ..user import User
from ..utils import get_args_and_clean
from .common import handle_error, get_req_id_from_ctx
from .request import Static, StaticForeign

logging.getLogger("discord").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

bot = commands.Bot(command_prefix="!")


class OnDemand(commands.Cog, name="On-demand requests"):
    """On-demand = executed instantly.

    Every user has three requests per day (one for GIFs). Patrons have
    unlimited requests."""

    static_handler = Static

    @commands.cooldown(1, 5, commands.BucketType.guild)
    @commands.command(name="req", **ClassicRequest.discord_help)
    async def request(self, ctx: commands.Context, *args):
        await self._handle_static(ctx, "!req", *args)

    @commands.cooldown(1, 5, commands.BucketType.guild)
    @commands.command(name="parallel", **ParallelRequest.discord_help)
    async def parallel(self, ctx: commands.Context, *args):
        await self._handle_static(ctx, "!parallel", *args)

    @commands.cooldown(1, 5, commands.BucketType.guild)
    @commands.command(name="palette", **PaletteRequest.discord_help)
    async def palette(self, ctx: commands.Context, *args):
        await self._handle_static(ctx, "!palette", *args)

    @commands.cooldown(1, 5, commands.BucketType.guild)
    @commands.command(name="swap", **SwapRequest.discord_help)
    async def swap(self, ctx: commands.Context, *args):
        await self._handle_static(ctx, "!swap", *args)

    async def _handle_static(self, ctx: commands.Context, prefix, *args):
        language_code = get_req_id_from_ctx(ctx)
        req = self.static_handler(bot, ctx, language_code, prefix, *args)
        await req.on_demand()


class OnDemandForeign(OnDemand):
    static_handler = StaticForeign


class Queue(commands.Cog, name="Queue requests to post on Facebook"):
    """Requests that will be added to the queue in order to get posted on
    the Facebook page.

    Every user has unlimited queue requests."""

    @commands.command(name="freq", **ClassicRequest.discord_help)
    async def request(self, ctx: commands.Context, *args):
        await self._handle_register(ctx, "!req", *args)

    @commands.command(name="fparallel", **ParallelRequest.discord_help)
    async def parallel(self, ctx: commands.Context, *args):
        await self._handle_register(ctx, "!parallel", *args)

    @commands.command(name="fpalette", **PaletteRequest.discord_help)
    async def palette(self, ctx: commands.Context, *args):
        await self._handle_register(ctx, "!palette", *args)

    @commands.command(name="fswap", **SwapRequest.discord_help)
    async def swap(self, ctx: commands.Context, *args):
        await self._handle_register(ctx, "!swap", *args)

    @staticmethod
    async def _handle_register(ctx: commands.Context, prefix, *args):
        language_code = get_req_id_from_ctx(ctx)
        req = Static(bot, ctx, language_code, prefix, *args)
        await req.register()


class Search(commands.Cog, name="Search in the database"):
    @commands.command(name="person", help="Search for cast and crew people.")
    async def person(self, ctx: commands.Context, *args):
        search = PersonSearch(" ".join(args), limit=1)
        search.search()

        for embed in search.embeds:
            await ctx.send(embed=embed)

    @commands.command(name="country", help="Search for a country.")
    async def country(self, ctx: commands.Context, *args):
        await self._meta_search_handler(ctx, args, CountrySearch)

    @commands.command(name="category", help="Search for a category.")
    async def category(self, ctx: commands.Context, *args):
        await self._meta_search_handler(ctx, args, CategorySearch)

    @commands.command(name="genre", help="Search for a genre.")
    async def genre(self, ctx: commands.Context, *args):
        await self._meta_search_handler(ctx, args, GenreSearch)

    @commands.command(name="movie", help="Search for movies.")
    async def movie(self, ctx: commands.Context, *args):
        movie = Movie.from_query(" ".join(args))
        await ctx.send(embed=movie.embed)

    @commands.command(name="tvshow", help="Search for TV Shows.")
    async def tvshow(self, ctx: commands.Context, *args):
        msearch = MediaFuzzySearch(" ".join(args), limit=1)
        msearch.search(table="tv_shows")

        for item in msearch.items:
            await ctx.send(embed=item.embed)

    @commands.command(name="request", help="Search for requests by content.")
    async def request(self, ctx: commands.Context, *args):
        rsearch = RequestSearch(" ".join(args))
        rsearch.search()

        await ctx.send(embed=rsearch.embed)

    @commands.cooldown(1, 15, commands.BucketType.guild)
    @commands.command(name="quote", help="Search for quotes.")
    async def quote(self, ctx: commands.Context, *args):
        language = get_req_id_from_ctx(ctx)
        query, args = get_args_and_clean(" ".join(args), ("--filter",))

        qsearch = QuoteSearch(query, filter_=args.get("filter", ""), lang=language)
        qsearch.search()

        await ctx.send(embed=qsearch.embed)

    @commands.command(name="song", help="Search for songs.")
    async def song(self, ctx: commands.Context, *args):
        ssearch = SongSearch(" ".join(args))
        ssearch.search()

        await ctx.send(embed=ssearch.embed)

    @commands.command(name="top", help="Show the top 10.", usage="FROM TO")
    async def top(self, ctx: commands.Context, from_=1, to_=10):
        top = TopMovies(limit=45)
        await ctx.send(top.discord((from_ - 1, to_)))

    @commands.cooldown(1, 5, commands.BucketType.guild)
    @commands.command(name="topusers", help="Show the top 10 users.", usage="FROM TO")
    async def topusers(self, ctx: commands.Context, from_=1, to_=10):
        top = TopUsers((from_ - 1, to_))
        await ctx.send(top.discord())

    @staticmethod
    async def _meta_search_handler(ctx: commands.Context, args, search_cls):
        search = search_cls(" ".join(args))
        search.search()

        await ctx.send(embed=search.embed)


_LANGUAGES_INDEX = {1: "en", 2: "es", 3: "pt"}


class MyUser(commands.Cog, name="User management"):
    @commands.command(name="queue", help="Show your queued requests.", usage="[User]")
    async def queue(self, ctx: commands.Context, *, member: Optional[Member] = None):
        if member is None:
            user = User.from_discord(ctx.author)
        else:
            user = User.from_discord(member)

        requests = [ClassicRequest(**item) for item in user.get_queued_requests()]

        await ctx.send("\n".join(req.pretty_title for req in requests)[:1000])

    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.command(name="badges", help="Show badges count.", usage="[User]")
    async def badges(
        self, ctx: commands.Context, *args, member: Optional[Member] = None
    ):
        if member is not None:
            user = User.from_discord(member)
        elif args:
            user = User.from_query(" ".join(args))
        else:
            user = User.from_discord(ctx.author)

        won_bdgs = user.get_badges()

        badges = [Badge(**item) for item in won_bdgs]
        table = self._tabulate_badges(badges)
        total_points_str = (
            f"`{user.name} total PRC 🇨🇳 social points: "
            f"{sum((bdg.points) for bdg in badges)}`"
        )

        await ctx.send("\n".join((table, total_points_str)))

    @staticmethod
    def _tabulate_badges(badges):
        badges = sorted(badges, key=attrgetter("points"), reverse=True)

        items = [("Title", "Collected", "Points")]
        items.extend((bdg.discord_tuple) for bdg in badges)

        return f"```{tabulate(items, headers='firstrow', tablefmt='github')}```"

    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.command(name="rate", help="Rate a movie (0.5-5).", usage="MOVIE X.X")
    async def rate(self, ctx: commands.Context, *args):
        try:
            rating = args[-1].split("/")[0]
        except IndexError:
            raise exceptions.InvalidRequest from None

        try:
            rating = float(rating)
        except ValueError:
            raise exceptions.InvalidRequest("Number not found: {rating}") from None

        logger.debug("Passed rating: %s", rating)

        movie = Movie.from_query(" ".join(args))
        user = User.from_discord(ctx.author)

        user.rate_media(movie, rating)
        await ctx.send(f"You rating for `{movie.simple_title}`: **{rating}/5**")

    @commands.command(name="upname", help="Update your username.")
    async def upname(self, ctx: commands.Context, *args):
        name = " ".join(args)

        user = User.from_discord(ctx.author)
        user.register()
        user.update_name(name)

        await ctx.send(f"Update name to `{name}` for user with `{user.id}` ID.")

    @commands.command(name="lang", help="Update the perma-language for your requests.")
    async def lang(self, ctx: commands.Context):
        def check_author(message):
            return message.author == ctx.author

        await ctx.send(
            f"Choose the language number (default: `1`):\n\n"
            "1. English\n2. Spanish\n3. Portuguese (Brazil)"
        )
        try:
            msg = await bot.wait_for("message", timeout=60, check=check_author)
            index = None
            try:
                index = int(msg.content.strip())
            except ValueError:
                pass

            if index is None or index not in _LANGUAGES_INDEX:
                raise exceptions.InvalidRequest("Invalid index")

            lang = _LANGUAGES_INDEX[index]
            user = User.from_discord(ctx.author)
            user.update_language(lang)
            await ctx.send(f"Your default language was updated to `{lang}`.")

        except asyncio.TimeoutError:
            pass


# No category
@commands.command(name="docs", help="Show documentation links.")
async def docs(ctx: commands.Context):
    await ctx.send(embed=API_HELP_EMBED)


@commands.command(name="server", help="Join Kinobot's official server.")
async def server(ctx: commands.Context):
    await ctx.send(DISCORD_INVITE)


@commands.command(name="invite", help="Invite the bot to your server.")
async def invite(ctx: commands.Context):
    await ctx.send(
        "The bot is under a verification process from Discord. "
        "This means you are no longer allowed to add the bot to "
        "any server until it gets verified. Starting the verification "
        "process at Jun 6, the process can take up four weeks. "
        "Please stay tuned."
    )


#    embed = Embed(title="Invite Kinobot to your server!")
#    embed.add_field(name="Prefixes", value="`k!`, `k.`", inline=False)
#    embed.add_field(
#        name="Invitation link",
#        value=f"[Click here]({DISCORD_BOT_INVITE})",
#        inline=False,
#    )
#    await ctx.send(embed=embed)


@commands.has_permissions(administrator=True)
@commands.command(name="where", help="Show bot guilds.")
async def where(ctx: commands.Context):
    guild_strs = [item.name for item in bot.guilds]
    msg = f"`Guilds: {', '.join(guild_strs[:1900])}\n\nTotal: {len(guild_strs)}`"
    await ctx.send(msg)


@bot.event
async def on_command_error(ctx: commands.Context, error):
    await handle_error(ctx, error)


@bot.event
async def on_ready():
    logger.info("Running on: %s (%s)", bot.user.name, bot.user.id)
    guild_strs = [item.name for item in bot.guilds]
    logger.info("Bot is ready. Guilds: %s", guild_strs)


def run(token: str, foreign: bool = False):
    bot.command_prefix = ["k!", "k."] if foreign else "!"
    reqs = OnDemandForeign if foreign else OnDemand

    logger.debug("Bot prefix: %s", bot.command_prefix)

    for cog in (reqs, Queue, MyUser, Search):
        bot.add_cog(cog(bot))

    for command in (docs, server, invite):
        bot.add_command(command)

    bot.run(token)
