import logging
import sqlite3
from random import randint, shuffle

import click
from discord import Embed, User, File
from discord.ext import commands

import kinobot.db as db
from kinobot import DISCORD_TOKEN, MEME_IMG
from kinobot.comments import dissect_comment
from kinobot.exceptions import (
    EpisodeNotFound,
    MovieNotFound,
    OffensiveWord,
    InvalidRequest,
)
from kinobot.request import search_episode, search_movie
from kinobot.utils import (
    check_current_playing_plex,
    get_id_from_discord,
    handle_kino_songs,
    is_episode,
)

db.create_discord_db()

bot = commands.Bot(command_prefix="!")

BASE = "https://kino.caretas.club"
GOOD_BAD = ("👍", "💩")
MOVIE_LIST = db.get_list_of_movie_dicts()
EPISODE_LIST = db.get_list_of_episode_dicts()


def handle_discord_request(ctx, command, args):
    request = " ".join(args)
    user_disc = ctx.author.name + ctx.author.discriminator
    username = db.get_name_from_discriminator(user_disc)

    try:
        request_dict = dissect_comment(f"!{command} {request}")
    except (MovieNotFound, EpisodeNotFound, OffensiveWord, InvalidRequest) as kino_exc:
        return f"Nope: {type(kino_exc).__name__}."

    request_id = str(randint(2000000, 5000000))

    if not request_dict:
        return "Invalid syntax."
    elif not username:
        return "You are not registered. Use `!register <YOUR NAME>`."

    try:
        db.insert_request(
            (
                username[0],
                request_dict["comment"],
                request_dict["command"],
                request_dict["title"],
                "|".join(request_dict["content"]),
                request_id,
                1,
            )
        )
        return f"Added. ID: {request_id}; user: {username[0]}."
    except sqlite3.IntegrityError:
        return "Duplicate request."


def handle_queue(queue, title):
    if queue:
        shuffle(queue)
        description = "\n".join(queue[:10])
        return Embed(title=title, description=description)
    return Embed(title=title, description="apoco si pa")


@bot.command(name="req", help="make a regular request")
async def request(ctx, *args):
    message = await ctx.send(handle_discord_request(ctx, "req", args))
    [await message.add_reaction(emoji) for emoji in GOOD_BAD]


@bot.command(name="parallel", help="make a parallel request")
async def parallel(ctx, *args):
    message = await ctx.send(handle_discord_request(ctx, "parallel", args))
    [await message.add_reaction(emoji) for emoji in GOOD_BAD]


@bot.command(name="palette", help="make a palette request")
async def palette(ctx, *args):
    message = await ctx.send(handle_discord_request(ctx, "palette", args))
    [await message.add_reaction(emoji) for emoji in GOOD_BAD]


@bot.command(name="register", help="register yourself")
async def register(ctx, *args):
    name = " ".join(args).title()
    discriminator = ctx.author.name + ctx.author.discriminator
    if not name:
        message = "Usage: `!register <YOUR NAME>`"
    elif not "".join(args).isalpha():
        message = "Invalid name."
    else:
        try:
            db.register_discord_user(name, discriminator)
            message = f"You were registered as '{name}'."
        except sqlite3.IntegrityError:
            old_name = db.get_name_from_discriminator(discriminator)[0]
            try:
                db.update_discord_name(name, discriminator)
                db.update_name_from_requests(old_name, name)
                message = f"Your name was updated: '{name}'."
            except sqlite3.IntegrityError:
                message = "Duplicate name."

    await ctx.send(message)


@bot.command(name="queue", help="get user queue")
async def queue(ctx, user: User = None):
    try:
        if user:
            name = db.get_name_from_discriminator(user.name + user.discriminator)[0]
            queue = db.get_user_queue(name)
        else:
            name = db.get_name_from_discriminator(
                ctx.author.name + ctx.author.discriminator
            )[0]
            queue = db.get_user_queue(name)
    except TypeError:
        return await ctx.send("User not registered.")

    await ctx.send(embed=handle_queue(queue, f"{name}' queue"))


@bot.command(name="pq", help="get priority queue")
async def priority_queue(ctx):
    queue = db.get_priority_queue()
    await ctx.send(embed=handle_queue(queue, "Priority queue"))


@bot.command(name="sr", help="search requests")
async def search_request_(ctx, *args):
    query = " ".join(args)
    requests = db.search_requests(query)

    if requests:
        shuffle(requests)
        description = "\n".join(requests[:5])
        embed = Embed(title=f"Results for '{query}'", description=description)
        return await ctx.send(embed=embed)

    await ctx.send("apoco si pa")


@bot.command(name="search", help="search for a movie or an episode")
async def search(ctx, *args):
    query = " ".join(args)
    try:
        if is_episode(query):
            result = search_episode(EPISODE_LIST, query, raise_resting=False)
            message = f"{BASE}/episode/{result['id']}"
        else:
            result = search_movie(MOVIE_LIST, query, raise_resting=False)
            message = f"{BASE}/movie/{result['tmdb']}"
    except (MovieNotFound, EpisodeNotFound):
        message = "apoco si pa"

    await ctx.send(message)


@bot.command(name="vs", help="verify subtitles")
@commands.has_any_role("botmin", "subs moderator")
async def verify_subs_(ctx):
    verified = db.verify_movie_subtitles()
    await ctx.send(f"OK. Total verified movie subtitles: **{verified}**.")


@bot.command(name="current", help="check if someone is verifying subtitles")
@commands.has_any_role("botmin", "subs moderator")
async def current(ctx, *args):
    check_list = check_current_playing_plex()
    if not check_list:
        return await ctx.send("Nobody is verifying subtitles.")
    await ctx.send(f"Current playing: **{', '.join(check_list)}**.")


@bot.command(name="list", help="get user list (admin-only)")
@commands.has_permissions(administrator=True)
async def user_list(ctx, *args):
    users = db.get_discord_user_list()
    embed = Embed(title="List of users", description=", ".join(users))
    await ctx.send(embed=embed)


@bot.command(name="sql", help="run a sql command on Kinobot's DB (admin-only)")
@commands.has_permissions(administrator=True)
async def sql(ctx, *args):
    command = " ".join(args)
    try:
        db.execute_sql_command(command)
        message = f"Command OK: {command}."
    except sqlite3.Error as sql_exc:
        message = f"Error: {sql_exc}."

    await ctx.send(message)


@bot.command(name="block", help="block an user by name (admin-only)")
@commands.has_permissions(administrator=True)
async def block(ctx, *args):
    user = " ".join(args)
    db.block_user(user.strip())
    await ctx.send("Ok.")


@bot.command(name="verify", help="verify a request by ID (admin-only)")
@commands.has_permissions(administrator=True)
async def verify(ctx, arg):
    await ctx.send(db.verify_request(arg.strip()))


@bot.command(name="song", help="add a song to kinosongs (admin-only)")
@commands.has_permissions(administrator=True)
async def song(ctx, arg=None):
    if not arg:
        await ctx.send(f"Randomly selected: {handle_kino_songs()}")
    else:
        handle_kino_songs(arg.strip())
        await ctx.send("Added.")


@bot.command(name="delete", help="delete a request by ID (admin-only)")
@commands.has_permissions(administrator=True)
async def delete(ctx, arg):
    await ctx.send(db.remove_request(arg.strip()))


@bot.command(name="purge", help="purge user requests by user (admin-only)")
@commands.has_permissions(administrator=True)
async def purge(ctx, user: User):
    try:
        user = db.get_name_from_discriminator(user.name + user.discriminator)[0]
    except TypeError:
        return await ctx.send("No requests found for given user")

    db.purge_user_requests(user)
    await ctx.send(f"Purged: {user}.")


@bot.event
async def on_message(message):
    try:
        embed_len = len(message.embeds[0].description)
    except IndexError:
        embed_len = 0

    if len(message.content) > 150 or embed_len > 500:
        channel = message.channel
        with open(MEME_IMG, "rb") as f:
            await channel.send(file=File(f))

    await bot.process_commands(message)


@bot.event
async def on_reaction_add(reaction, user):
    if user.bot or not str(reaction) in GOOD_BAD or "botmin" != str(user.top_role):
        return

    channel = bot.get_channel(reaction.message.channel.id)
    content = reaction.message.content
    item_id = get_id_from_discord(content)

    if content.startswith("Added") and str(reaction) == GOOD_BAD[1]:
        return await channel.send(db.remove_request(item_id))

    if content.startswith("Possible NSFW") and str(reaction) == GOOD_BAD[0]:
        return await channel.send(db.verify_request(item_id))


@click.command("discord")
def discord_bot():
    " Run discord Bot. "
    logging.basicConfig(level=logging.INFO)
    bot.run(DISCORD_TOKEN)
