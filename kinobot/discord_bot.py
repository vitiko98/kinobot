# Only used for notifications of NSFW content.

import click
from discord.ext import commands

from kinobot import DISCORD_TOKEN
from kinobot.db import block_user, verify_request

bot = commands.Bot(command_prefix="!")


@bot.command(name="verify", help="verify request by ID")
async def verify(ctx, arg):
    try:
        verify_request(arg.strip())
        await ctx.send(f"Request {arg} successfully verified.")
    except Exception as error:
        await ctx.send(f"Something went wrong: {error}.")


@bot.command(name="block", help="block an user by request ID")
async def block(ctx, *args):
    try:
        user = " ".join(args)
        block_user(user.strip())
        await ctx.send(f"User {user} successfully blocked.")
    except Exception as error:
        await ctx.send(f"Something went wrong: {error}.")


@click.command("discord")
def discord_bot():
    " Run discord Bot. "
    bot.run(DISCORD_TOKEN)
