#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

# Discord bot for the official Kinobot server.

import logging
import os
import shutil
from typing import Optional

from discord import Member
from discord.ext import commands

import kinobot.exceptions as exceptions

from ..badge import InteractionBadge, StaticBadge
from ..constants import API_HELP_EMBED, SERVER_PATH
from ..media import Movie
from ..request import ClassicRequest, GifRequest, PaletteRequest, ParallelRequest
from ..search import (
    CategorySearch,
    CountrySearch,
    GenreSearch,
    MediaFuzzySearch,
    PersonSearch,
    QuoteSearch,
    RequestSearch,
)
from ..user import User
from ..utils import get_args_and_clean
from .common import handle_error
from .request import Static

logging.getLogger("discord").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

bot = commands.Bot(command_prefix="!")


class OnDemand(commands.Cog, name="On-demand requests"):
    """On-demand = executed instantly.

    Every user has three requests per day (one for GIFs). Patrons have
    unlimited requests."""

    @commands.command(name="req", help=ClassicRequest.__doc__)
    async def request(self, ctx: commands.Context, *args):
        await self._handle_static(ctx, ClassicRequest, *args)

    @commands.command(name="parallel", help=ParallelRequest.__doc__)
    async def parallel(self, ctx: commands.Context, *args):
        await self._handle_static(ctx, ParallelRequest, *args)

    @commands.command(name="palette", help=PaletteRequest.__doc__)
    async def palette(self, ctx: commands.Context, *args):
        await self._handle_static(ctx, PaletteRequest, *args)

    @commands.command(name="gif", help=GifRequest.__doc__)
    async def gif(self, ctx: commands.Context, *args):
        req_ = GifRequest.from_discord(args, ctx)

        await ctx.send("Getting GIF...")

        handler = req_.get_handler(user=User.from_discord(ctx.author))
        image = handler.get()[0]

        final_path = os.path.join(SERVER_PATH, os.path.basename(image))

        shutil.move(image, final_path)
        logger.info("GIF moved: %s -> %s", image, final_path)

        await ctx.send("XD")

    @staticmethod
    async def _handle_static(ctx: commands.Context, req_cls, *args):
        req = Static(bot, ctx, req_cls, *args)
        await req.on_demand()


class Queue(commands.Cog, name="Queue requests to post on Facebook"):
    """Requests that will be added to the queue in order to get posted on
    the Facebook page.

    Every user has unlimited queue requests."""

    @commands.command(name="freq", help=ClassicRequest.__doc__)
    async def request(self, ctx: commands.Context, *args):
        await self._handle_register(ctx, ClassicRequest, *args)

    @commands.command(name="fparallel", help=ParallelRequest.__doc__)
    async def parallel(self, ctx: commands.Context, *args):
        await self._handle_register(ctx, ParallelRequest, *args)

    @commands.command(name="fpalette", help=PaletteRequest.__doc__)
    async def palette(self, ctx: commands.Context, *args):
        await self._handle_register(ctx, PaletteRequest, *args)

    @staticmethod
    async def _handle_register(ctx: commands.Context, req_cls, *args):
        req = Static(bot, ctx, req_cls, *args)
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
        msearch = MediaFuzzySearch(" ".join(args), limit=1)
        msearch.search()

        for item in msearch.items:
            await ctx.send(embed=item.embed)

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

    @commands.command(name="quote", help="Search for quotes.")
    async def quote(self, ctx: commands.Context, *args):
        query, args = get_args_and_clean(" ".join(args), ("--filter",))

        qsearch = QuoteSearch(query, filter_=args.get("filter", ""))
        qsearch.search()

        await ctx.send(embed=qsearch.embed)

    @staticmethod
    async def _meta_search_handler(ctx: commands.Context, args, search_cls):
        search = search_cls(" ".join(args))
        search.search()

        await ctx.send(embed=search.embed)


class MyUser(commands.Cog, name="User management"):
    @commands.command(name="queue", help="Show your queued requests.", usage="[User]")
    async def queue(self, ctx: commands.Context, *, member: Optional[Member] = None):
        if member is None:
            user = User.from_discord(ctx.author)
        else:
            user = User.from_discord(member)

        requests = [ClassicRequest(**item) for item in user.get_queued_requests()]

        await ctx.send("\n".join(req.pretty_title for req in requests)[:1000])

    @commands.command(name="badges", help="Show badges count.", usage="[User]")
    async def badges(self, ctx: commands.Context, *, member: Optional[Member] = None):
        if member is None:
            user = User.from_discord(ctx.author)
        else:
            user = User.from_discord(member)

        won_bdgs = user.get_badges()

        badges = [*InteractionBadge.__subclasses__(), *StaticBadge.__subclasses__()]

        won_bdgs_ = []
        for badge in badges:
            for won in won_bdgs:
                if badge.id == won["badge_id"]:
                    won_bdgs_.append(badge(**won))

        badge_list_str = "\n".join(badge.discord_title for badge in won_bdgs_)
        total_points_str = (
            f"`Total People's Republic of China social points`: "
            f"**{sum((bdg.points) for bdg in won_bdgs_)}**"
        )

        await ctx.send("\n\n".join((badge_list_str, total_points_str)))

    @commands.command(name="rate", help="Rate a movie (0.5-5).", usage="MOVIE X.X")
    async def rate(self, ctx: commands.Context, *args):
        rating = args[-1].split("/")[0]

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


# No category
@commands.command(name="docs", help="Show documentation links.")
async def docs(ctx: commands.Context):
    await ctx.send(embed=API_HELP_EMBED)


@bot.event
async def on_command_error(ctx: commands.Context, error):
    await handle_error(ctx, error)


def run(token: str, prefix: str = "!"):
    bot.command_prefix = prefix

    for cog in commands.Cog.__subclasses__():
        bot.add_cog(cog(bot))

    bot.add_command(docs)

    bot.run(token)
