import asyncio

from discord.ext.commands import Context
from discord.file import File

from kinobot.request import Request
from kinobot.user import User


async def review(ctx: Context):
    requests = Request.randoms_from_queue(verified=True)
    loop = asyncio.get_event_loop()

    for request in requests:
        await ctx.send(f"Loading request [{request.id}]...")

        try:
            handler = await loop.run_in_executor(None, request.get_handler)
            images = await loop.run_in_executor(None, handler.get)
        except Exception as error:
            await ctx.send(f"{type(error).__name__} raised")
            await ctx.send(str(request.id))
            await ctx.send(f"{'x'*20}\nNEXT\n{'x'*20}")
            continue

        user = User(id=request.user_id)
        user.load(register=True)
        msg = f"**{user.name}**\nRequest title: **{request.facebook_pretty_title}**\nPost title: **{handler.title}**\nID:"

        await ctx.send(msg)
        await ctx.send(str(request.id))

        for image in images:
            await ctx.send(file=File(image))

        await ctx.send(f"{'x'*20}\nNEXT\n{'x'*20}")

    await ctx.send(
        "Please check carefully titles, usernames, quotes and images.\nDelete any offending requests with !delete <ID>."
    )
