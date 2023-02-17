#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

# Discord bot for admin tasks.

import asyncio
import datetime
from datetime import date
import functools
import logging
import re

from discord import channel
from discord import Member
from discord.ext import commands
import pysubs2

from ..constants import DISCORD_ANNOUNCER_WEBHOOK
from ..constants import KINOBASE
from ..constants import YAML_CONFIG
from ..db import Execute
from ..exceptions import InvalidRequest
from ..frame import FONTS_DICT
from ..jobs import register_media
from ..media import Episode
from ..media import Movie
from ..metadata import Category
from ..post import register_posts_metadata
from ..register import FacebookRegister
from ..request import get_cls
from ..user import User
from ..utils import get_yaml_config
from ..utils import is_episode
from ..utils import send_webhook
from ..utils import sync_local_subtitles
from .chamber import Chamber
from .chamber import CollaborativeChamber
from .common import get_req_id_from_ctx
from .common import handle_error
from .extras.curator import MovieView
from .extras.curator import RadarrClient
from .extras.curator import register_movie_addition
from .extras.curator import register_tv_show_season_addition
from .extras.curator import ReleaseModel
from .extras.curator import ReleaseModelSonarr
from .extras.curator import SonarrClient
from .extras.curator import SonarrTVShowModel
from .extras.curator_user import Curator
from .extras.verification import UserDB as VerificationUser
from .extras.verifier import Poster
from .extras.verifier import Verifier

# from .extras import subtitles

logging.getLogger("discord").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

bot = commands.Bot(command_prefix="!")


def _get_cls_from_ctx(ctx):
    return get_cls(get_req_id_from_ctx(ctx))


@bot.command(name="averify", help="Verify a request by ID.")
@commands.has_any_role("botmin")
async def admin_verify(ctx: commands.Context, id_: str):
    req = _get_cls_from_ctx(ctx).from_db_id(id_)
    req.verify()

    await ctx.send(f"Verified: {req.pretty_title}")


@bot.command(name="verify", help="Verify a request by ID.")
async def verify(ctx: commands.Context, id_: str):
    request = _get_cls_from_ctx(ctx).from_db_id(id_)
    if request.verified:
        return await ctx.send("This request was already verified")

    loop = asyncio.get_running_loop()

    await ctx.send("Loading request...")
    handler = await call_with_typing(ctx, loop, None, request.get_handler)
    await call_with_typing(ctx, loop, None, handler.get)

    with VerificationUser(ctx.author.id, KINOBASE) as user:
        risk = request.facebook_risk()
        if risk is not None:
            await ctx.send(
                f"WARNING: there's a possible facebook-risky pattern: `{risk}`. "
                "Please delete it if you feel this request could get the page banned "
                "from Facebook."
            )

        used_ticket = user.log_ticket(request.id)
        request.verify()

    await ctx.send(f"{request.pretty_title} **verified with ticket**: {used_ticket}")


@bot.command(name="tickets", help="Show tickets count.")
async def tickets(ctx: commands.Context):
    with VerificationUser(ctx.author.id, KINOBASE) as user:
        tickets = user.tickets()
        available_tickets = user.available_tickets()

    await ctx.send(
        f"Available tickets: {len(available_tickets)}\n"
        f"Total tickets: {len(tickets)}"
    )


@bot.command(name="fonts", help="Get the list of available fonts")
async def fonts(ctx: commands.Context):
    keys = [f"**{font}**" for font in FONTS_DICT.keys()]
    await ctx.send(f"Available fonts:\n\n{', '.join(keys)}")


@bot.command(name="rfi", help="Get request string from ID")
async def req_from_id(ctx: commands.Context, id: str):
    req = _get_cls_from_ctx(ctx).from_db_id(id)
    await ctx.send(req.comment)


@bot.command(name="gticket", help="Give verification tickets")
@commands.has_any_role("botmin")
async def gticket(ctx: commands.Context, user: Member, tickets, *args):
    summary = (
        f"Gave by admin in {datetime.datetime.now().strftime('%m/%d/%Y, %H:%M:%S')}"
    )

    with VerificationUser(user.id, KINOBASE) as v_user:
        for _ in range(int(tickets)):
            v_user.append_ticket(summary=summary)

        available_tickets = v_user.available_tickets()

    await ctx.send(
        f"{tickets} tickets registered for {user.display_name}\n"
        f"Available tickets: {len(available_tickets)}"
    )


@bot.command(name="gpack", help="Give pack from currency")
@commands.has_any_role("botmin")
async def gpack(ctx: commands.Context, user: Member, currency, *args):
    currency = float(currency)
    await gkey(ctx, user, currency * 4)
    await gticket(ctx, user, int(currency))


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

    if chamber.unique_count >= 50:
        await ctx.send("50 or more requests seen. Members will get 1 GB.")
        # Shouldn't be private!
        for member_id in chamber._member_ids():
            await _gkey(ctx, 1.0, member_id, "From chamber")


@commands.has_any_role("botmin", "verifier")
@bot.command(name="schamber", help="Enter the verification chamber.")
async def schamber(ctx: commands.Context):
    chamber = Chamber(bot, ctx)
    await chamber.start()


@bot.command(name="count", help="Show the count of verified requests.")
async def count(ctx: commands.Context):
    req_cls = _get_cls_from_ctx(ctx)
    await ctx.send(
        f"Verified requests: {Execute().queued_requets(table=req_cls.table)}"
    )


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


@commands.has_any_role("botmin")
@bot.command(name="fsub", help="Change subtitles timestamp")
async def fsub(ctx: commands.Context, *args):
    time = args[-1].strip()
    try:
        sec, mss = [int(item) for item in time.split(".")]
    except ValueError:
        raise InvalidRequest(f"Invalid timestamps: {time}")

    query = " ".join(args).replace(time, "")
    if is_episode(query):
        item = Episode.from_query(query)
    else:
        item = Movie.from_query(query)

    subs = pysubs2.load(item.subtitle)
    subs.shift(s=sec, ms=mss)

    await ctx.send(f"Shifted `{sec}s:{mss}ms`. Type `reset` to restore it.")

    try:
        msg = await bot.wait_for("message", timeout=60, check=_check_botmin)

        if "reset" in msg.content.lower().strip():
            subs.shift(s=-sec, ms=-mss)
            await ctx.send("Restored.")

    except asyncio.TimeoutError:
        pass

    subs.save(item.subtitle)

    await ctx.send(f"Subtitles updated for `{item.pretty_title}`.")


@commands.has_any_role("botmin")
@bot.command(name="cat", help="Add category to a random untagged movie.")
async def cat(ctx: commands.Context, *args):
    if not args:
        movie = Movie(**Category.random_untagged_movie())
    else:
        movie = Movie.from_query(" ".join(args))

    await ctx.send(f"Tell me the new category for {movie.simple_title}:")

    try:
        msg = await bot.wait_for("message", timeout=60, check=_check_botmin)

        if "pass" not in msg.content.lower().strip():
            category = Category(name=msg.content.strip().title())
            category.register_for_movie(movie.id)
            await ctx.send(embed=movie.embed)
        else:
            await ctx.send("Ignored.")

    except asyncio.TimeoutError:
        await ctx.send("Bye")


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

    await ctx.send(msg)


async def call_with_typing(ctx, loop, *args):
    result = None
    async with ctx.typing():
        result = await loop.run_in_executor(*args)

    return result


_MIN_BYTES = 1e9


def _pretty_gbs(bytes_):
    return f"{bytes_/float(1<<30):,.1f} GBs"


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

    await _pretty_title_list(ctx, movie_views)

    chosen_index = await _interactive_index(ctx, movies)

    if chosen_index is None:
        return None

    chosen_movie_view = movie_views[chosen_index]
    if chosen_movie_view.already_added():  # or chosen_movie_view.to_be_added():
        return await ctx.send("This movie is already in the database.")

    await ctx.send(embed=chosen_movie_view.embed())
    await ctx.send("Are you sure? (y/n)")

    sure = await _interactive_y_n(ctx)
    if sure is None:
        return None

    if not sure:
        return await ctx.send("Dumbass (jk)")

    result = await call_with_typing(
        ctx, loop, None, client.add, movies[chosen_index], False
    )

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
    await _pretty_title_list(ctx, models[:20], append_txt)

    chosen_index = await _interactive_index(ctx, models)
    if chosen_index is None:
        return None

    await ctx.send("Are you sure? (y/n)")

    model_1 = models[chosen_index]

    if model_1.size > size_left:
        return await ctx.send("You don't have enough GBs available.")

    sure = await _interactive_y_n(ctx)
    if sure is None:
        return None

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
    if sure is None:
        return None

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

    append_txt = (
        "Expected quality: **Blu-ray > WEB-DL > WEBrip/DVD > Others**.\n**Bitrate > Resolution** "
        "(most cases). Subtitles are harder to get for HDTV releases.\nAsk admin if you are not "
        "sure about releases that require manual import."
    )
    await _pretty_title_list(ctx, models[:20], append_txt)

    chosen_index = await _interactive_index(ctx, models)
    if chosen_index is None:
        return None

    await ctx.send("Are you sure? (y/n)")

    model_1 = models[chosen_index]

    if model_1.size > size_left:
        return await ctx.send("You don't have enough GBs available.")

    sure = await _interactive_y_n(ctx)
    if sure is None:
        return None

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
async def gkey(ctx: commands.Context, user: Member, gbs, *args):
    await _gkey(ctx, gbs, user.id, " ".join(args))


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


async def _gkey(ctx, gbs, user_id, note):
    bytes_ = int(_GB * float(gbs))

    with Curator(user_id, KINOBASE) as curator:
        curator.register_key(bytes_, note)

    await ctx.send(f"Key of {gbs} GBs registered for user:{user_id}")


@bot.command(name="gbs", help="Get GBs free to use for curator tasks")
async def gbs(ctx: commands.Context):
    with Curator(ctx.author.id, KINOBASE) as curator:
        size_left = curator.size_left()

    await ctx.send(_pretty_gbs(size_left))


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


# @bot.command(name="report", help="Report bad subtitles", usage="MOVIE/EPISODE query")
async def report_subtitles(ctx: commands.Context, *args):
    subtitles = None

    query = " ".join(args)
    episode = is_episode(query)
    media_item = _media_from_query(query)

    await ctx.send(
        "Please tell us what's wrong with the subtitles of "
        f"**{media_item.pretty_title}**.\n"
        "Be serious; repeated bad reports are a cause of ban. "
        "Type **'no'** if you want to finish this operation."
    )

    summary = await _ask(ctx, timeout=300)
    if summary is None:
        await ctx.send(f"Bye {ctx.author.display_name}")
        return None

    with subtitles.SubtitlesUser(ctx.author.id, KINOBASE) as s_user:
        if episode is True:
            s_user.fill_episode_report(
                media_item.tv_show.id, media_item.season, media_item.episode, summary
            )
        else:
            s_user.fill_movie_report(media_item.id, summary)

    await ctx.send("Thanks for your report!")


# bot.command(name="fixsub", help="Fix subtitles", usage="MOVIE/EPISODE query")
async def fix_subtitles(ctx: commands.Context, *args):
    query = " ".join(args)
    media_item = _media_from_query(query)
    await ctx.send(
        f"Search subtitles for {media_item.pretty_title}? (y/n) "
        "Remember: you'll get banned if you verify bad subtitles or replace "
        "already good subtitles."
    )

    response = await _ask(ctx, return_none_string="n")
    if response is None:
        await ctx.send(f"Bye {ctx.author.display_name}")
        return None

    await ctx.send("Searching...")

    video = subtitles.source_to_video(media_item)

    client = subtitles.Client(subtitles.SubtitlesConfig.from_file("envs/subtitles.yml"))
    loop = None

    subs_ = await call_with_typing(ctx, loop, client.list_subtitles, video)

    await ctx.send(
        f"Choose the subtitle to download for {video.name}:\n{_pretty_subtitles_list(subs_)}"
    )
    index = await _interactive_index(ctx, subs_)
    if index is None:
        return None

    chosen_sub = subs_[index]
    await ctx.send("Downloading subtitle. Please wait...")
    await call_with_typing(ctx, loop, client.download_subtitle, video, chosen_sub)
    await ctx.send(
        "Subtitle downloaded. Please verify it (not in this channel) and then come back. "
        "Type 'good' if they are perfect; type 'again' to chose another subtitle; type 'no' "
        "to finish this operation."
    )


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


@bot.event
async def on_command_error(ctx: commands.Context, error):
    await handle_error(ctx, error)


_SHUT_UP_BOI = "Bra shut up boi 💯"
_GOAR_RE = re.compile(r"\b(carti|kanye|ye)\b")
_DUMMY_RE = re.compile(r"\b(jojo|verifiers?|anime|letterbox|lbxd|mubi|art|american?)\b")


@bot.listen("on_message")
async def shut_up_boi(message):
    if message.content.startswith("!"):
        return None

    if (message.author.id == bot.user.id) or message.webhook_id:
        return None

    if "840093068711165982" != str(message.channel.id):
        return None

    if "💯" in message.content:
        await message.channel.send(_SHUT_UP_BOI, reference=message)

    elif _GOAR_RE.search(message.content.lower()):
        await message.channel.send("🐐", reference=message)

    elif _DUMMY_RE.search(message.content.lower()):
        await message.channel.send(
            "https://media.discordapp.net/attachments/840093068711165982/1047240153539821568/unknown.png",
            reference=message,
        )


def _check_botmin(message):
    return str(message.author.top_role) == "botmin"


def run(token: str, prefix: str):
    bot.command_prefix = prefix

    bot.run(token)
