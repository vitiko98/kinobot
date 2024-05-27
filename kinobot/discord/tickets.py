from discord.ext import commands

from kinobot.config import config
from kinobot.constants import KINOBASE
from kinobot.request import Request
from kinobot.user import User
from kinobot.utils import send_webhook

from .extras.verification import UserDB as VerificationUser


async def verify(ctx: commands.Context, id_: str):
    request = Request.from_db_id(id_)
    if request.verified:
        return await ctx.send("This request was already verified")

    for item in ("!manga", "!comic", "!yt"):
        if item in request.comment:
            return await ctx.send(f"{item} forbidden for tickets")

    with VerificationUser(ctx.author.id, KINOBASE) as user:
        used_ticket = user.log_ticket(request.id)
        request.verify()

    await ctx.send(f"{request.pretty_title} **verified with ticket**: {used_ticket}.")

    request.load_user()
    send_webhook(config.webhooks.ticket_filter, f"{request.user.name} | {request.id}")
    send_webhook(config.webhooks.ticket_filter, request.comment)


async def approve(ctx: commands.Context, id):
    request = Request.from_db_id(id)
    if request.verified:
        return await ctx.send("This request was already verified")

    request.user.load()

    request.verify()

    send_webhook(
        config.webhooks.tickets,
        f"**[Check passed]**\n{request.comment[:400]}\n**by**\n{request.user.name}",
    )
    await ctx.send(f"OK: {request.comment}")


async def reject(ctx: commands.Context, id, *args):
    if not args:
        return await ctx.send("Need a reason.")

    reason = " ".join(args)
    request = Request.from_db_id(id)
    if request.verified:
        request.mark_as_used()

    request.mark_as_used()

    request.user.load()

    with VerificationUser(request.user.id, KINOBASE) as user:
        user.append_ticket(summary="Refund")

    send_webhook(
        config.webhooks.tickets,
        f"**[Check not passed - Ticket refunded]**\n{request.comment[:400]}\n**by**\n{request.user.name}\n\nReason: {reason}",
    )
    await ctx.send("Ok.")
