# Experimenting with Discord bots.

import logging
import sqlite3
from random import randint, shuffle

import click
from discord.ext import commands
from discord import Embed, User

from kinobot.exceptions import OffensiveWord, MovieNotFound, EpisodeNotFound
from kinobot import DISCORD_TOKEN, REQUESTS_DB
from kinobot.comments import dissect_comment
from kinobot.db import (
    block_user,
    create_discord_db,
    get_name_from_discriminator,
    get_user_queue,
    get_list_of_episode_dicts,
    get_list_of_movie_dicts,
    get_discord_user_list,
    insert_request,
    register_discord_user,
    purge_user_requests,
    update_name_from_requests,
    verify_request,
    remove_request,
    update_discord_name,
    execute_sql_command,
)
from kinobot.request import search_movie, search_episode
from kinobot.utils import is_name_invalid, is_episode

create_discord_db()

bot = commands.Bot(command_prefix="!")

BASE = "https://kino.caretas.club"
MOVIE_LIST = get_list_of_movie_dicts()
EPISODE_LIST = get_list_of_episode_dicts()


@bot.command(name="req", help="make a regular request")
async def request(ctx, *args):
    request = " ".join(args)
    user_disc = ctx.author.name + ctx.author.discriminator
    username = get_name_from_discriminator(user_disc)

    try:
        request_dict = dissect_comment("!req " + request)
    except (MovieNotFound, EpisodeNotFound, OffensiveWord) as kino_exc:
        return await ctx.send(f"Nope: {type(kino_exc).__name__}.")

    request_id = str(randint(20000000, 50000000))

    if not request_dict:
        message = "Invalid syntax. Usage: `!req TITLE [{quote,timestamp}]...`"
    elif not username:
        message = "You are not registered. Use `!register <YOUR NAME>`."
    else:
        try:
            insert_request(
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
            message = f"Added. (User: `{username[0]}`; ID: `{request_id}`)."
        except sqlite3.IntegrityError:
            message = "Duplicate request."

    await ctx.send(message)


@bot.command(name="register", help="register yourself")
async def register(ctx, *args):
    name = " ".join(args).title()
    discriminator = ctx.author.name + ctx.author.discriminator
    if not name:
        message = "Usage: `!register <YOUR NAME>`"
    elif is_name_invalid(name):
        message = "Invalid name."
    else:
        try:
            register_discord_user(name, discriminator)
            message = f"You were registered as '{name}'."
        except sqlite3.IntegrityError:
            old_name = get_name_from_discriminator(discriminator)[0]
            update_discord_name(name, discriminator)
            update_name_from_requests(old_name, name)
            message = f"Your name was updated: '{name}'."

    await ctx.send(message)


@bot.command(name="verify", help="verify a request by ID (admin-only)")
@commands.has_permissions(administrator=True)
async def verify(ctx, arg):
    verify_request(arg.strip())
    await ctx.send("Ok.")


@bot.command(name="delete", help="delete a request by ID (admin-only)")
@commands.has_permissions(administrator=True)
async def delete(ctx, arg):
    remove_request(arg.strip())
    await ctx.send(f"Deleted: {arg}.")


@bot.command(name="purge", help="purge user requests by user (admin-only)")
@commands.has_permissions(administrator=True)
async def purge(ctx, user: User):
    try:
        user = get_name_from_discriminator(user.name + user.discriminator)[0]
    except TypeError:
        return await ctx.send("No requests found for given user")

    purge_user_requests(user)
    await ctx.send(f"Purged: {user}.")


@bot.command(name="queue", help="get user queue")
async def queue(ctx, user: User = None):
    try:
        if user:
            user_ = get_name_from_discriminator(user.name + user.discriminator)[0]
            queue = get_user_queue(user_)
        else:
            discriminator = ctx.author.name + ctx.author.discriminator
            name = get_name_from_discriminator(discriminator)[0]
            queue = get_user_queue(name)
    except TypeError:
        return await ctx.send("User not registered.")

    if queue:
        shuffle(queue)
        embed = Embed(title=f"{name}'s queue", description="\n".join(queue[:10]))
        await ctx.send(embed=embed)
    else:
        await ctx.send("No requests found.")


@bot.command(name="list", help="get user list (admin-only)")
@commands.has_permissions(administrator=True)
async def user_list(ctx, *args):
    users = get_discord_user_list()
    embed = Embed(title="List of users", description=", ".join(users))
    await ctx.send(embed=embed)


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
        message = "Nothing found."

    await ctx.send(message)


@bot.command(name="sql", help="run a sql command on Kinobot's DB (admin-only)")
@commands.has_permissions(administrator=True)
async def sql(ctx, *args):
    command = " ".join(args)
    try:
        # Probably using subcommands here is better (?)
        if command.startswith("requests"):
            command = command[7:].strip()
            execute_sql_command(command, database=REQUESTS_DB)
        else:
            execute_sql_command(command)
        message = f"Command OK: {command}."
    except sqlite3.Error as sql_exc:
        message = f"Error: {sql_exc}."

    await ctx.send(message)


@bot.command(name="block", help="block an user by name (admin-only)")
@commands.has_permissions(administrator=True)
async def block(ctx, *args):
    user = " ".join(args)
    block_user(user.strip())
    await ctx.send("Ok.")


@click.command("discord")
def discord_bot():
    " Run discord Bot. "
    logging.basicConfig(level=logging.INFO)
    bot.run(DISCORD_TOKEN)
