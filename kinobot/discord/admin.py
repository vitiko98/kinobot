#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

# Discord bot for admin tasks.

import asyncio
import datetime
import functools
import logging
import os
import re
import subprocess
from typing import Optional

from discord import channel
from discord import Member
from discord.ext import commands
import pysubs2

from kinobot.discord.extras import subtitles as d_subtitles
from kinobot.discord.utils import paginated_list
from kinobot.misc import bonus

from . import anime
from . import review
from . import sports
from . import utils
from . import jackpot
from . import wrapped as wrapped_module
from ..constants import KINOBASE
from ..constants import YAML_CONFIG
from ..db import Execute
from ..exceptions import InvalidRequest
from ..frame import FONTS_DICT
from ..jobs import post_to_facebook
from ..jobs import register_media
from ..media import Episode
from ..media import Movie
from ..post import register_posts_metadata
from ..register import FacebookRegister
from ..request import get_cls
from ..request import Request
from ..user import User
from ..utils import get_yaml_config
from ..utils import is_episode
from ..utils import sync_local_subtitles
from .chamber import Chamber
from .chamber import CollaborativeChamber
from .comics import curate as comic_curate
from .comics import explorecomics
from .common import get_req_id_from_ctx
from . import video as video_module
from .common import handle_error
from .extras.announcements import top_contributors
from .extras.curator import MovieView
from .extras.curator import RadarrClient
from .extras.curator import register_movie_addition
from .extras.curator import register_tv_show_season_addition
from .extras.curator import ReleaseModel
from .extras.curator import ReleaseModelSonarr
from .extras.curator import SonarrClient
from .extras.curator import SonarrTVShowModel
from .extras.curator_user import AnimeCurator
from .extras.curator_user import Curator
from .extras.verification import IGUserDB as IGVerificationUser
from .extras.verification import UserDB as VerificationUser
from .extras.verifier import Poster
from .extras.verifier import Verifier
from .games import addgame
from .games import deletecutscene
from .games import explorecutscenes
from .games import exploregames
from .instagram import ig_poster
from .instagram import make_post
from .mangas import addchapter
from .mangas import addmanga
from .mangas import exploremangas
from .ochamber import OldiesChamber
from .request_trace import trace_checks
from .songs import addsong
from .songs import exploresongs
from .tickets import approve as approve_
from .tickets import reject as reject_
from .tickets import verify as verify_
from . import emby

logging.getLogger("discord").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

bot = commands.Bot(command_prefix="!")


def _get_cls_from_ctx(ctx):
    return get_cls(get_req_id_from_ctx(ctx))


@bot.command(name="bonus", help="Check bonus.")
@commands.has_any_role("botmin")
async def run_bonus(ctx):
    loop = asyncio.get_running_loop()

    await call_with_typing(ctx, loop, None, bonus.run)
    await ctx.send("Ok.")


@bot.command(name="averify", help="Verify a request by ID.")
@commands.has_any_role("botmin")
async def admin_verify(ctx: commands.Context, id_: str):
    req = _get_cls_from_ctx(ctx).from_db_id(id_)
    req.mark_as_unused()
    req.verify()

    await ctx.send(f"Verified: {req.pretty_title}")


@bot.command(name="aigverify", help="Verify an IG request by ID.")
@commands.has_any_role("botmin")
async def admin_ig_verify(ctx: commands.Context, id_: str):
    req = _get_cls_from_ctx(ctx).from_db_id(id_)
    req.add_tag("ig")
    req.verify()

    await ctx.send(f"Verified: {req.pretty_title}")


@bot.command(name="review", help="Review requests from the FB queue.")
@commands.has_any_role("botmin", "verifier")
async def review_(ctx: commands.Context):
    await review.review(ctx)


@bot.command(name="esub", help="Upload subtitles")
@commands.has_any_role("botmin", "subtitles")
async def esub(ctx: commands.Context):
    await d_subtitles.edit(bot, ctx)


@bot.command(name="usub", help="Upload subtitles")
@commands.has_any_role("botmin", "subtitles")
async def usub(ctx: commands.Context):
    await d_subtitles.upload(bot, ctx)


@bot.command(name="ssub", help="Shift subtitles by milliseconds")
@commands.has_any_role("botmin", "subtitles")
async def ssub(ctx: commands.Context):
    await d_subtitles.shift(bot, ctx)


@bot.command(name="asub", help="Try to sync subtitles automatically with alass")
@commands.has_any_role("botmin", "subtitles")
async def asub(ctx: commands.Context):
    await d_subtitles.autosync(bot, ctx)


@bot.command(name="clone", help="Clone a request to queue.")
@commands.has_any_role("botmin")
async def clone(ctx: commands.Context, id_: str, tag=None):
    request = _get_cls_from_ctx(ctx).from_db_id(id_)
    new = request.clone()

    if tag is None:
        new.add_tag(tag)

    new.verify()

    await ctx.send(str(new.id))


@bot.command(name="verify", help="Verify a request by ID.")
@commands.has_any_role("botmin", "maoist", "super-maoist", "sponsor", "ticketer")
async def verify(ctx: commands.Context, id_: str):
    await verify_(ctx, id_)


@bot.command(name="approve", help="Approve a request by ID.")
@commands.has_any_role("botmin", "certified verifier")
async def approve(ctx: commands.Context, id_: str):
    await approve_(ctx, id_)


@bot.command(name="reject", help="Reject a request by ID.")
@commands.has_any_role("botmin", "certified verifier")
async def reject(ctx: commands.Context, id_: str, *args):
    await reject_(ctx, id_, *args)


# @bot.command(name="igverify", help="Verify an IG request by ID.")
async def igverify(ctx: commands.Context, id_: str):
    request = _get_cls_from_ctx(ctx).from_db_id(id_)
    if request.verified:
        return await ctx.send("This request was already verified")

    loop = asyncio.get_running_loop()

    await ctx.send("Loading request...")
    handler = await call_with_typing(ctx, loop, None, request.get_handler)
    await call_with_typing(ctx, loop, None, handler.get)

    bad = await trace_checks(ctx, handler.make_trace())

    if bad is False:
        risk = request.facebook_risk()
        if risk is not None:
            await ctx.send(
                f"WARNING: there's a possible facebook-risky pattern: `{risk}`."
            )
            bad = True

    if bad is True:
        return await ctx.send(
            "You are not allowed to verify this. If you believe this request is fine, ask the administrator "
            "for manual verification. You can also remove the offending content/flag and try verifying again."
        )

    with IGVerificationUser(ctx.author.id, KINOBASE) as user:
        used_ticket = user.log_ticket(request.id)
        request.add_tag("ig")
        request.verify()

    await ctx.send(f"{request.pretty_title} **verified with ticket**: {used_ticket}")


@bot.command(name="emsetup", help="Setup your Jellyfin/Emby wrapped data.")
async def emsetup(ctx: commands.Context):
    await emby.setup(bot, ctx)


@bot.command(name="vid", help="Run video command.")
async def video(ctx: commands.Context, *args):
    try:
        with video_module.deduct_token(ctx.author.id):
            await video_module.make(ctx, args)
    except video_module.NoBalance:
        await ctx.send(
            "You don't have any tokens to use. Donate to get tokens https://ko-fi.com/vitiko"
        )


@bot.command(name="lastplayed", help="Run your last played.")
async def lastplayed(ctx: commands.Context, *args):
    await emby.run(bot, ctx, " ".join(args))


@bot.command(name="tickets", help="Show tickets count.")
async def tickets(ctx: commands.Context):
    if str(ctx.author.id) == "336777437646028802":
        return await ctx.send("This user has unlimited tickets")

    with VerificationUser(ctx.author.id, KINOBASE) as user:
        available_tickets = user.available_tickets()
        expired_tickets = user.expired_tickets()

    await ctx.send(
        f"Available tickets: {len(available_tickets)}\n"
        f"Expired tickets: {len(expired_tickets)}\n\n"
    )


@bot.command(name="fonts", help="Get the list of available fonts")
async def fonts(ctx: commands.Context):
    fonts = sorted(list(FONTS_DICT.keys()))
    keys = [f"**{font}**" for font in fonts]
    await ctx.send(f"Available fonts:\n\n{', '.join(keys)}"[:999])


@bot.command(name="rfi", help="Get request string from ID")
async def req_from_id(ctx: commands.Context, id: str):
    req = _get_cls_from_ctx(ctx).from_db_id(id)
    await ctx.send(req.comment)


@bot.command(name="collab", help="Add an user to a request as a collaborator")
async def collab(ctx: commands.Context, user: Member, request_id: str):
    req = Request.from_db_id(request_id)

    author_id = str(ctx.author.id)
    if req.user_id != author_id:
        return await ctx.send("You are not the author of the request.")

    req.add_collaborator(user.id)
    await ctx.send(f"Added *{user.id}* as a collaborator for {req.comment}")


@bot.command(name="gpayout", help="Add payout")
@commands.has_any_role("botmin")
async def gpayout(ctx: commands.Context, user: Member, amount: int):
    result = jackpot.add_payout(user.id, amount * 100)
    return await ctx.send(str(result))


@bot.command(name="gticket", help="Give verification tickets")
@commands.has_any_role("botmin")
async def gticket(ctx: commands.Context, user: Member, tickets, days=90):
    summary = (
        f"Gave by admin in {datetime.datetime.now().strftime('%m/%d/%Y, %H:%M:%S')}"
    )

    with VerificationUser(user.id, KINOBASE) as v_user:
        for _ in range(int(tickets)):
            v_user.append_ticket(
                summary=summary, expires_in=datetime.timedelta(days=int(days))
            )

        available_tickets = v_user.available_tickets()

    await ctx.send(
        f"{tickets} tickets registered for {user.display_name}\n"
        f"Available tickets: {len(available_tickets)}"
    )


@bot.command(name="givejackpot", help="Give yesterday's jackpot")
@commands.has_any_role("botmin")
async def givejackpot(ctx: commands.Context):
    jackpot.give_jackpot()


@bot.command(name="currentjackpot", help="See current jackpot")
@commands.has_any_role("botmin")
async def currentjackpot(ctx: commands.Context):
    jackpot.get_current_jackpot()


@bot.command(name="gigticket", help="Give verification tickets")
@commands.has_any_role("botmin")
async def gigticket(ctx: commands.Context, user: Member, tickets, days=90):
    summary = (
        f"Gave by admin in {datetime.datetime.now().strftime('%m/%d/%Y, %H:%M:%S')}"
    )

    with IGVerificationUser(user.id, KINOBASE) as v_user:
        for _ in range(int(tickets)):
            v_user.append_ticket(
                summary=summary, expires_in=datetime.timedelta(days=int(days))
            )

        available_tickets = v_user.available_tickets()

    await ctx.send(
        f"{tickets} IG tickets registered for {user.display_name}\n"
        f"Available IG tickets: {len(available_tickets)}"
    )


@bot.command(name="gpack", help="Give pack from currency")
@commands.has_any_role("botmin")
async def gpack(ctx: commands.Context, currency, *users: Member):
    days = 90
    currency = float(currency)
    for user in users:
        await gkey(ctx, user, currency * 3, days=int(days))
        await gticket(ctx, user, int(currency), days=int(days))
        await video_module.give_tokens(ctx, user, int(currency * 20))


@bot.command(name="gtokens", help="Give tokens")
@commands.has_any_role("botmin")
async def gtokens(ctx: commands.Context, user: Member, amount, *args):
    await video_module.give_tokens(ctx, user, int(amount * 20))


@bot.command(name="rtokens", help="Remove available tokens")
@commands.has_any_role("botmin")
async def rtokens(ctx: commands.Context, user: Member, amount, *args):
    await video_module.remove_tokens(ctx, user, amount)


@bot.command(name="rticket", help="Remove available tickets")
@commands.has_any_role("botmin")
async def rticket(ctx: commands.Context, user: Member, tickets, *args):
    with VerificationUser(user.id, KINOBASE) as v_user:
        v_user.delete_tickets(int(tickets))
        available_tickets = v_user.available_tickets()

    await ctx.send(
        f"{tickets} tickets removed for {user.display_name}.\n"
        f"Available tickets: {len(available_tickets)}"
    )


@bot.command(name="delete", help="Mark as used a request by ID.")
@commands.has_any_role("botmin", "verifier")
async def delete(ctx: commands.Context, id_: str):
    req = _get_cls_from_ctx(ctx).from_db_id(id_)
    req.mark_as_used()
    await ctx.send(f"Marked as used: {req.pretty_title}")


@commands.has_any_role("botmin", "verifier")
@bot.command(name="chamber", help="Enter the verification chamber.")
async def chamber(ctx: commands.Context, *args):
    chamber = await CollaborativeChamber.from_bot(bot, ctx, args)
    await chamber.start()


@commands.has_any_role("botmin", "certified verifier")
@bot.command(name="schamber", help="Enter the verification chamber.")
async def schamber(ctx: commands.Context):
    await ctx.send(
        "Requests newer than N days. Send any alphabetical character to allow any request."
    )
    msg = await utils.ask(bot, ctx)

    try:
        newer_than = datetime.timedelta(days=int(msg))
    except:
        newer_than = None

    await ctx.send("Private chamber? (y/n)")
    msg = await utils.ask(bot, ctx)

    try:
        private = msg.lower() == "y"
    except:
        private = False

    await ctx.send("Avoid multiple images (y/n)")
    msg = await utils.ask(bot, ctx)

    try:
        no_multiple_images = msg.lower() == "y"
    except:
        no_multiple_images = False

    await ctx.send(
        "Exclude requests containing the following keywords. Send a single character to allow any request."
    )
    msg = await utils.ask(bot, ctx)
    exclude_list = None
    if msg:
        exclude_list = [item for item in msg.split() if len(item.strip()) > 1]
        if not exclude_list:
            exclude_list = None

    chamber = Chamber(
        bot,
        ctx,
        newer_than=newer_than,
        exclude_if_contains=exclude_list,
        no_multiple_images=no_multiple_images,
        private=private,
    )
    await chamber.start()


@commands.has_any_role("botmin")
@bot.command(name="ochamber", help="Enter the oldies verification chamber.")
async def ochamber(ctx: commands.Context):
    chamber = OldiesChamber(bot, ctx)
    await chamber.start()


@bot.command(name="count", help="Show the count of verified requests.")
async def count(ctx: commands.Context):
    req_cls = _get_cls_from_ctx(ctx)
    await ctx.send(
        f"Verified requests: {Execute().queued_requets(table=req_cls.table)}"
    )

    await ctx.send(
        f"Verified requests (300k): {Execute().queued_requets(table=req_cls.table, tag='300k')}"
    )


@commands.has_any_role("botmin")
@bot.command(name="makeig")
async def makeig(ctx: commands.Context, id=None):
    loop = asyncio.get_running_loop()
    await call_with_typing(ctx, loop, None, ig_poster, id)
    await ctx.send("Ok.")


@bot.command(name="ig")
async def ig(ctx: commands.Context, *args):
    req = _get_cls_from_ctx(ctx)(
        " ".join(args), ctx.author.id, ctx.author.name, ctx.message.id
    )
    req.register()
    req.add_tag("ig")

    await ctx.send(req.id)


@commands.has_any_role("botmin")
@bot.command(name="scan", help="Scan facebook comments")
async def scan(ctx: commands.Context, count: int):
    await ctx.send(f"Scanning {count} posts per page...")

    loop = asyncio.get_running_loop()

    for identifier in ("en", "es", "pt"):
        register = FacebookRegister(int(count), identifier)
        await call_with_typing(ctx, loop, None, register.requests)

    await ctx.send("Done.")


def _media_from_query(query):
    if is_episode(query):
        return Episode.from_query(query)

    return Movie.from_query(query)


@commands.has_any_role("botmin")
@bot.command(name="blacklist", help="Blacklist a movie or an episode")
async def blacklist(ctx: commands.Context, *args):
    query = " ".join(args)
    item = _media_from_query(query)
    item.hidden = True
    item.update()
    await ctx.send(f"Blacklisted: {item.simple_title}.")


@commands.has_any_role("botmin")
@bot.command(name="media", help="Register media")
async def media(ctx: commands.Context):
    await ctx.send("Registering media")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, register_media)
    await ctx.send("Ok")


@commands.has_any_role("botmin")
@bot.command(name="fbpost", help="Post to Facebook")
async def fbpost(ctx: commands.Context):
    await ctx.send("Running Facebook loop...")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, post_to_facebook)
    await ctx.send("Ok")


@commands.has_any_role("botmin")
@bot.command(name="insights", help="Register insights")
async def insights(ctx: commands.Context, days: str, to_hours=12):
    from_ = datetime.datetime.now() - datetime.timedelta(days=int(days))
    to_ = datetime.datetime.now() - datetime.timedelta(hours=int(to_hours))

    config = get_yaml_config(YAML_CONFIG, "facebook")

    loop = asyncio.get_running_loop()

    for key, val in config.items():
        await ctx.send(f"Scanning '{key}' insights")
        await loop.run_in_executor(
            None,
            functools.partial(
                register_posts_metadata, val["insights_token"], from_, to_, False
            ),
        )

    await ctx.send("Done.")


@commands.has_any_role("botmin")
@bot.command(name="syncsubs", help="Sync local subtitles")
async def syncsubs(ctx: commands.Context):
    await ctx.send("Syncing local subtitles")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, sync_local_subtitles)
    await ctx.send("Ok")


def _check_author(author):
    return lambda message: message.author == author


async def _interactive_index(ctx, items):
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


async def _interactive_int_index(ctx, items):
    try:
        msg = await bot.wait_for(
            "message", timeout=120, check=_check_author(ctx.author)
        )
        try:
            selected = int(msg.content.lower().strip())
            if selected not in items:
                raise ValueError

            return selected
        except ValueError:
            await ctx.send("Invalid index! Bye")
            return None

    except asyncio.TimeoutError:
        await ctx.send("Timeout! Bye")
        return None


async def _interactive_y_n(ctx):
    try:
        msg = await bot.wait_for(
            "message", timeout=120, check=_check_author(ctx.author)
        )
        return msg.content.lower().strip() == "y"
    except asyncio.TimeoutError:
        return await ctx.send("Timeout! Bye")


async def _pretty_title_list(ctx, items, append=None):
    str_list = "\n".join(f"{n}. {m.pretty_title()}" for n, m in enumerate(items, 1))
    msg = f"Choose the item you want to add ('n' to ignore):\n\n{str_list}"

    if append is not None:
        msg = f"{msg}\n\n{append}"

    await ctx.send(msg[:1999])


async def call_with_typing(ctx, loop, *args):
    result = None
    async with ctx.typing():
        result = await loop.run_in_executor(*args)

    return result


_MIN_BYTES = 1e9


def _pretty_gbs(bytes_):
    return f"{bytes_/float(1<<30):,.1f} GBs"


@bot.command(name="updateanime", help="Update anime")
async def updateanime(ctx: commands.Context, *args):
    await anime.update(bot, ctx)


# @bot.command(name="addan", help="Add anime")
async def addan(ctx: commands.Context, *args):
    await anime.add(bot, ctx, *args)


@bot.command(name="addc", help="Add comic issues")
async def addc(ctx: commands.Context, *args):
    with Curator(ctx.author.id, KINOBASE) as curator:
        size_left = curator.size_left()

    def bytes_callback(bytes_):
        return size_left >= bytes_

    item = await comic_curate(bot, ctx, " ".join(args), bytes_callback)
    try:
        assert item.bytes
    except AttributeError:
        return None

    with Curator(ctx.author.id, KINOBASE) as curator:
        curator.register_addition(item.bytes, note="comic")


@bot.command(name="cutscenes", help="Search for cutscenes from a game")
async def cutscene_(ctx: commands.Context, *args):
    return await explorecutscenes(bot, ctx, *args)


@bot.command(name="addmatch", help="Add a sports match")
async def addmatch(ctx: commands.Context, video_url):
    return await sports.add(bot, ctx, video_url)


@bot.command(name="matches", help="Explore sports matches")
async def matches(ctx: commands.Context, *args):
    return await sports.explore(bot, ctx, *args)


@bot.command(name="games", help="Search for games")
async def games_(ctx: commands.Context, *args):
    return await exploregames(bot, ctx, *args)


@bot.command(name="delcutscene", help="Delete a cutscene")
async def delcutscene(ctx: commands.Context, *args):
    return await deletecutscene(bot, ctx, " ".join(args))


@bot.command(name="addg", help="Add a game cutscene to the database.")
async def addgame_(ctx: commands.Context, video_url, *args):
    return await addgame(bot, ctx, video_url, *args)


@bot.command(name="addmangach", help="Add a manga chapter by ID or URL.")
async def addmangach_(ctx: commands.Context, url):
    return await addchapter(bot, ctx, url)


@bot.command(name="addmanga", help="Add a manga title to the database.")
async def addmanga_(ctx: commands.Context, video_url, *args):
    return await addmanga(bot, ctx, video_url, *args)


@bot.command(name="mangas", help="Search for manga titles")
async def mangas_(ctx: commands.Context, video_url, *args):
    return await exploremangas(bot, ctx, video_url, *args)


@bot.command(name="comics", help="Search for comics")
async def comics_(ctx: commands.Context, *args):
    return await explorecomics(bot, ctx, *args)


@bot.command(name="adds", help="Add a song music video to the database.")
@commands.has_any_role("botmin", "music_curator")
async def addsong_(ctx: commands.Context, video_url, *args):
    return await addsong(bot, ctx, video_url, *args)


@bot.command(name="contribs")
@commands.has_any_role("botmin")
async def contribs(ctx: commands.Context):
    top_contributors()


@bot.command(name="songs", help="Search for songs by artist or title")
async def songs_(ctx: commands.Context, *args):
    return await exploresongs(bot, ctx, *args)


@bot.command(name="addm", help="Add a movie to the database.")
async def addmovie(ctx: commands.Context, *args):
    with Curator(ctx.author.id, KINOBASE) as curator:
        size_left = curator.size_left()

    if size_left < _MIN_BYTES:
        return await ctx.send(
            f"You need at least a quota of 1 GB to use this feature. You have {_pretty_gbs(size_left)}."
        )

    query = " ".join(args)

    user = User.from_discord(ctx.author)
    user.load()

    loop = asyncio.get_running_loop()

    try:
        client = await call_with_typing(ctx, loop, None, RadarrClient.from_constants)
    except Exception as error:
        logger.error(error, exc_info=True)
        return await ctx.send(
            "This curator feature is not available at the moment. Please "
            "try again later."
        )

    movies = await call_with_typing(ctx, loop, None, client.lookup, query)
    movies = movies[:10]

    movie_views = [MovieView(movie) for movie in movies]

    chosen_movie_view = await paginated_list(
        bot, ctx, "Movies", movie_views, lambda d: d.pretty_title()
    )
    if chosen_movie_view is None:
        return None

    chosen_movie = [
        movie
        for movie in movies
        if movie.get("tmdbId") == chosen_movie_view.data.get("tmdbId")
    ][0]

    if chosen_movie_view.already_added():  # or chosen_movie_view.to_be_added():
        await ctx.send(
            "WARNING. This movie is already in the database. "
            "Update it only if it's an upgrade, otherwise it will fail."
        )

    await ctx.send(embed=chosen_movie_view.embed())
    await ctx.send("Are you sure? (y/n)")

    sure = await _interactive_y_n(ctx)
    if not sure:
        await ctx.send("Bye.")
        return None

    result = await call_with_typing(ctx, loop, None, client.add, chosen_movie, False)

    pretty_title = f"**{chosen_movie_view.pretty_title()}**"

    await ctx.send("Looking for releases")
    manual_r = await call_with_typing(
        ctx, loop, None, client.manual_search, result["id"]
    )

    models = [ReleaseModel(**item) for item in manual_r]
    models = [
        model for model in models if model.seeders and "Unknown" != model.quality.name
    ]
    if not models:
        return await ctx.send("No releases found.")

    models.sort(key=lambda x: x.size, reverse=False)

    append_txt = (
        "Expected quality: **Blu-ray > WEB-DL > WEBrip/DVD > Others**.\n**Bitrate > Resolution** "
        "(most cases).\nAsk admin if you are not sure about releases "
        "that require manual import; your GBs won't be recovered."
    )
    chosen_model = await paginated_list(
        bot, ctx, "Releases", models, lambda d: d.pretty_title(), slice_in=10
    )
    #    await _pretty_title_list(ctx, models[:20], append_txt)

    if not chosen_model:
        return None
    #    chosen_index = await _interactive_index(ctx, models)
    #    if chosen_index is None:
    #        return None

    await ctx.send("Are you sure? (y/n)")

    model_1 = chosen_model

    if model_1.size > size_left:
        return await ctx.send("You don't have enough GBs available.")

    sure = await _interactive_y_n(ctx)
    if not sure:
        return await ctx.send("Bye.")

    await loop.run_in_executor(
        None,
        client.add_to_download_queue,
        model_1.movie_id,
        model_1.guid,
        model_1.indexer_id,
    )

    register_movie_addition(user.id, chosen_movie_view.tmdb_id)

    with Curator(ctx.author.id, KINOBASE) as curator:
        curator.register_addition(model_1.size, "Made via curator command")
        new_size_left = curator.size_left()

    await ctx.send(
        f"Getting the release. Let's wait.\nGBs left: {_pretty_gbs(new_size_left)}"
    )

    await asyncio.sleep(10)

    retries = 0
    grabbed_event_sent = False

    while 45 > retries:
        events = await loop.run_in_executor(
            None, client.events_in_history, result["id"]
        )
        for event in events:
            if event == "downloadFolderImported":
                return await ctx.reply(f"{pretty_title} is ready!")

            if event == "grabbed" and not grabbed_event_sent:
                grabbed_event_sent = True
                # await ctx.reply(
                #    f"Good news: {pretty_title} is being imported. Let's wait..."
                # )
            else:
                logger.debug("Unknown event: %s", event)

        retries += 1
        await asyncio.sleep(60)

    if grabbed_event_sent:
        await ctx.reply(
            f"{pretty_title} is taking too much time to import. Botmin will "
            "have a look if the issue persists."
        )
    else:
        await ctx.reply(
            f"Impossible to add {pretty_title} automatically. Botmin will check it manually."
        )


@bot.command(name="addtv", help="Add a TV Show's season to the database.")
async def addtvshow(ctx: commands.Context, *args):
    with Curator(ctx.author.id, KINOBASE) as curator:
        size_left = curator.size_left()

    if size_left < _MIN_BYTES:
        return await ctx.send(
            f"You need at least a quota of 1 GB to use this feature. You have {_pretty_gbs(size_left)}."
        )

    query = " ".join(args)

    user = User.from_discord(ctx.author)
    user.load()

    loop = asyncio.get_running_loop()

    try:
        client = await call_with_typing(ctx, loop, None, SonarrClient.from_constants)
    except Exception as error:
        logger.error(error, exc_info=True)
        return await ctx.send(
            "This curator feature is not available at the moment. Please "
            "try again later."
        )

    items = await call_with_typing(ctx, loop, None, client.lookup, query)
    tv_models = [SonarrTVShowModel(**item) for item in items[:10]]

    await _pretty_title_list(ctx, tv_models)

    chosen_index = await _interactive_index(ctx, tv_models)

    if chosen_index is None:
        return None

    chosen_tv = tv_models[chosen_index]

    await ctx.send(embed=chosen_tv.embed())
    await ctx.send("Are you sure? (y/n)")

    sure = await _interactive_y_n(ctx)
    if not sure:
        return await ctx.send("Bye")

    result = await call_with_typing(
        ctx, loop, None, client.add, items[chosen_index], False
    )
    series_id = result["id"]

    valid_seasons = [i.season_number for i in chosen_tv.seasons if i.season_number]
    await ctx.send(f"Select the season: {', '.join(str(i) for i in valid_seasons)}")
    chosen_season = await _interactive_int_index(ctx, valid_seasons)
    if chosen_season is None:
        return None

    await ctx.send(
        f"Looking for releases [{chosen_tv.pretty_title()} Season {chosen_season}]"
    )
    manual_r = await call_with_typing(
        ctx,
        loop,
        None,
        client.manual_search,
        result["id"],
        chosen_season,
    )

    models = [ReleaseModelSonarr(**item, seriesId=series_id) for item in manual_r]  # type: ignore
    models = [model for model in models if model.seeders]
    if not models:
        return await ctx.send("No releases found.")

    models.sort(key=lambda x: x.size, reverse=False)

    # append_txt = (
    #   "Expected quality: **Blu-ray > WEB-DL > WEBrip/DVD > Others**.\n**Bitrate > Resolution** "
    #   "(most cases). Subtitles are harder to get for HDTV releases.\nAsk admin if you are not "
    #   "sure about releases that require manual import."

    # )
    model_1 = await paginated_list(
        bot, ctx, "Releases", models, lambda d: d.pretty_title(), slice_in=10
    )
    if model_1 is None:
        return None

    await ctx.send("Are you sure? (y/n)")

    if model_1.size > size_left:
        return await ctx.send("You don't have enough GBs available.")

    sure = await _interactive_y_n(ctx)
    if not sure:
        return await ctx.send("Bye.")

    await loop.run_in_executor(
        None,
        client.add_to_download_queue,
        model_1.guid,
        model_1.indexer_id,
    )

    register_tv_show_season_addition(user.id, chosen_tv.tvdb_id, chosen_season)

    with Curator(ctx.author.id, KINOBASE) as curator:
        curator.register_addition(model_1.size, "Made via curator command")
        new_size_left = curator.size_left()

    await ctx.send(
        f"Getting the release. Let's wait.\nGBs left: {_pretty_gbs(new_size_left)} "
        "Check #announcements."
    )


_GB = float(1 << 30)


@bot.command(name="gkey", help="Give a curator key")
@commands.has_any_role("botmin")
async def gkey(ctx: commands.Context, user: Member, gbs, days=90, *args):
    await _gkey(ctx, gbs, user.id, " ".join(args), days=int(days))


@bot.command(name="gkeya", help="Give an anime curator key")
@commands.has_any_role("botmin")
async def gkeya(ctx: commands.Context, user: Member, gbs, days=90, *args):
    await _gkey(ctx, gbs, user.id, " ".join(args), days=int(days), cls_=AnimeCurator)


@bot.command(name="vtop", help="Show verifiers top")
async def vtop(ctx: commands.Context):
    with Verifier(ctx.author.id, KINOBASE) as verifier:
        result = verifier.get_top(
            between=(None, datetime.datetime.now() - datetime.timedelta(hours=12))
        )

    await ctx.send(f"```{result.as_table()}```")


@bot.command(name="utop", help="Show users top")
async def utop(ctx: commands.Context):
    with Poster(ctx.author.id, KINOBASE) as poster:
        result = poster.get_top(
            between=(None, datetime.datetime.now() - datetime.timedelta(hours=12))
        )

    await ctx.send(f"```{result.as_table()}```")


@bot.command(name="ucard", help="Show users top card")
async def ucard(ctx: commands.Context):
    with Poster(ctx.author.id, KINOBASE) as poster:
        result = poster.get_top_card(
            between=(None, datetime.datetime.now() - datetime.timedelta(hours=12))
        )

    await ctx.send(f"```{result}```")


async def _gkey(ctx, gbs, user_id, note, days=90, cls_=None):
    bytes_ = int(_GB * float(gbs))
    cls_ = cls_ or Curator

    with cls_(user_id, KINOBASE) as curator:
        curator.register_key(
            bytes_, note, expires_in=datetime.timedelta(days=int(days))
        )

    await ctx.send(
        f"Key of {gbs} [{type(cls_).__name__}] GBs registered for user:{user_id}"
    )


@bot.command(name="topyear", help="Get current year's top posts")
async def topyear(ctx: commands.Context, user: Optional[Member] = None):
    if user is None:
        user_ = User.from_discord(ctx.author)
    else:
        user_ = User.from_discord(user)

    user_.load()

    result = jackpot.get_yearly_top(user_.id, user_.name)
    await ctx.send(result)


@bot.command(name="wrapped", help="Get current year's wrapped")
async def wrapped(ctx: commands.Context, user: Optional[Member] = None):
    if user is None:
        avatar_url = ctx.author.avatar_url
        user = User.from_discord(ctx.author)
    else:
        avatar_url = user.avatar_url
        user = User.from_discord(user)

    user.load()

    try:
        await wrapped_module.make(ctx, user.id, user.name, avatar_url)
    except wrapped_module.NoData:
        await ctx.send("Not enough data for this user.")


@bot.command(name="wrappedall", help="Get all time wrapped")
async def wrapped_all(ctx: commands.Context, user: Optional[Member] = None):
    if user is None:
        avatar_url = ctx.author.avatar_url
        user = User.from_discord(ctx.author)
    else:
        avatar_url = user.avatar_url
        user = User.from_discord(user)

    user.load()

    await wrapped_module.make(ctx, user.id, user.name, avatar_url, True)


@bot.command(name="tokens", help="Get tokens free to use")
async def tokens(ctx: commands.Context):
    await video_module.get_balance(ctx, ctx.author)


@bot.command(name="gbs", help="Get GBs free to use for curator tasks")
async def gbs(ctx: commands.Context):
    if str(ctx.author.id) == "336777437646028802":
        return await ctx.send("This user has unlimited GBs")

    with Curator(ctx.author.id, KINOBASE) as curator:
        size_left = curator.size_left()
        # expired_size_left = curator.expired_bytes_no_use()
        # lifetime = curator.lifetime_used_bytes()

    with AnimeCurator(ctx.author.id, KINOBASE) as curator:
        size_left_anime = curator.size_left()

    await ctx.send(
        f"Available GBs: {_pretty_gbs(size_left)}\n"
        f"Available Anime GBs: {_pretty_gbs(size_left_anime)}"
    )


@bot.command(name="gbsa", help="Get Anime GBs free to use for curator tasks")
async def gbsa(ctx: commands.Context):
    with AnimeCurator(ctx.author.id, KINOBASE) as curator:
        size_left = curator.size_left()
        # expired_size_left = curator.expired_bytes_no_use()
        # lifetime = curator.lifetime_used_bytes()

    await ctx.send(f"Available Anime GBs: {_pretty_gbs(size_left)}")


async def _ask(ctx, timeout=120, return_none_string="no"):
    try:
        msg = await bot.wait_for(
            "message", timeout=timeout, check=_check_author(ctx.author)
        )
        content = msg.content.strip()
        if content.lower() == return_none_string:
            return None

        return content
    except asyncio.TimeoutError:
        return None


def _pretty_subtitles_list(subtitles):
    strs = [
        f"**{num}.** {sub.release_info} (score: {sub.score})"
        for num, sub in enumerate(subtitles, 1)
    ]
    return "\n".join(strs)


@bot.command(name="getid", help="Get an user ID by search query.")
@commands.has_any_role("botmin", "verifier")
async def getid(ctx: commands.Context, *args):
    user = User.from_query(" ".join(args))
    await ctx.send(f"{user.name} ID: {user.id}")


@bot.command(name="checkfont", help="Check fonts.")
@commands.has_any_role("botmin")
async def checkfont(ctx: commands.Context, *args):
    req_str = " ".join(args)

    from kinobot.frame import FONTS_DICT
    from .request import Static

    filtered = ("heavy", "bold", "hinted", "semi", "black")
    filtered_2 = ("obliq", "italic")
    fonts = []
    for font in FONTS_DICT.keys():
        if any(fd in font.lower() for fd in filtered) and not any(
            fd in font.lower() for fd in filtered_2
        ):
            fonts.append(font)

    await ctx.send(f"About to check {len(fonts)} fonts!")

    for item in fonts:
        new_req_str = f"{req_str} --font {item}"
        static = Static(bot, ctx, "en", "!req", *new_req_str.split())
        await ctx.send("-------------\n" + item)
        try:
            await static.on_demand(embed=False)
        except:
            await ctx.send("Error")


@bot.command(name="maintenance", help="Maintenance.")
@commands.has_any_role("botmin", "sponsor")
async def maintenance(ctx: commands.Context, *args):
    await ctx.send("Checking system status...")

    def _run():
        subprocess.run(os.environ["MAINTENANCE_COMMAND"])

    loop = asyncio.get_running_loop()
    await call_with_typing(ctx, loop, _run)

    await ctx.send("Everything seems okay for now.")


@bot.event
async def on_command_error(ctx: commands.Context, error):
    await handle_error(ctx, error)


_SHUT_UP_BOI = "Bra shut up boi 💯"
_GOAT_RE = re.compile(r"\b(yeat|bad bunny|kanye|ye|lizard)\b")


@bot.listen("on_message")
async def shut_up_boi(message):
    if message.content.startswith("!"):
        return None

    if (message.author.id in (bot.user.id, "597554387212304395")) or message.webhook_id:
        return None

    if "840093068711165982" != str(message.channel.id):
        return None

    if "💯" in message.content:
        await message.channel.send(_SHUT_UP_BOI, reference=message)

    elif _GOAT_RE.search(message.content.lower()):
        await message.channel.send("🐐", reference=message)

    return None


def _check_botmin(message):
    return str(message.author.top_role) == "botmin"


def run(token: str, prefix: str):
    bot.command_prefix = prefix

    bot.run(token)
