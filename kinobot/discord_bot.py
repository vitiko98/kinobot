# Experimenting with Discord bots.

import logging
import sqlite3
from random import randint

import click
from discord.ext import commands

from kinobot import DISCORD_TOKEN
from kinobot.comments import dissect_comment
from kinobot.db import (
    block_user,
    create_discord_db,
    get_name_from_discriminator,
    insert_request,
    register_discord_user,
    verify_request,
    remove_request,
    update_discord_name,
)

create_discord_db()

bot = commands.Bot(command_prefix="!")


@bot.command(name="req", help="make a regular request")
async def request(ctx, *args):
    request = " ".join(args)
    user_disc = ctx.author.name + ctx.author.discriminator
    username = get_name_from_discriminator(user_disc)
    request_dict = dissect_comment("!req " + request)
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
            message = f"Added to the database (ID: `{request_id}`)."
        except sqlite3.IntegrityError:
            message = "Duplicate request."

    await ctx.send(message)


@bot.command(name="register", help="register yourself")
async def register(ctx, *args):
    name = " ".join(args)
    discriminator = ctx.author.name + ctx.author.discriminator
    if not name:
        message = "Usage: `!register <YOUR NAME>`"
    else:
        try:
            register_discord_user(name, discriminator)
            message = f"You were registered as '{name}'."
        except sqlite3.IntegrityError:
            update_discord_name(name, discriminator)
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
