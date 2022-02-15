#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import asyncio
import functools
import logging
import time

from discord import Embed, File
from discord.ext import commands

from ..request import Request
from ..user import ForeignUser, User

_GOOD_BAD = ("👍", "💩")

logging.getLogger("discord").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


class Static:
    "Class for the Discord request commands."
    user_handler = User

    def __init__(
        self,
        bot: commands.Bot,
        ctx: commands.Context,
        identifier="en",
        prefix="!req",
        *args,
    ):
        self.bot = bot
        self.ctx = ctx
        self._identifier = identifier
        self._req = Request.from_discord(args, self.ctx, identifier, prefix)

        logger.debug("Request instance: %s", self._req)

        self._handler = None
        self._started = time.time()

    async def on_demand(self):
        "Perform an on-demand request."
        await self._load_handler()
        await self.ctx.send(embed=self.embed)
        await self._send_images()

    async def register(self):
        "Register the request and the user. Ask for removal once registered."
        self._req.register()
        await self._ask_remove()

    @property
    def finished(self) -> str:
        """A message showing the time passed since the instance's start.

        :rtype: str
        """
        return f"Task finished in {round(time.time() - self._started, 2)} seconds"

    @property
    def embed(self) -> Embed:
        """An embed containing the handler title and the finished time.

        :rtype: Embed
        """
        assert self._handler is not None

        embed = Embed(title=self._handler.title[:250])
        embed.set_footer(
            text=f"{self.finished} | {self._req.user.remain_requests} | {self._identifier}"
        )

        return embed

    async def _load_handler(self):
        loop = asyncio.get_running_loop()

        user = self.user_handler.from_discord(self.ctx.author)
        self._handler = await loop.run_in_executor(
            None, functools.partial(self._req.get_handler, user=user)
        )
        async with self.ctx.typing():
            # Temporary catch
            try:
                assert await loop.run_in_executor(None, self._handler.get)
            except:
                if user.unlimited is False:
                    user.substract_role_limit()
                raise

    async def _send_images(self):
        for image in self._handler.images:
            logger.info("Sending info: %s", image)
            await self.ctx.send(file=File(image))

    async def _ask_remove(self):
        msg = await self.ctx.send(
            f"Registered: `{self._req.id}` (request for: {self._identifier}). "  # fixme
            "You have 60 seconds to react with the poop to discard the request."
        )

        await msg.add_reaction(_GOOD_BAD[1])

        try:
            reaction, user = await self.bot.wait_for(
                "reaction_add", timeout=60, check=self._check_react
            )
            assert user

            if str(reaction) == str(_GOOD_BAD[1]):
                self._req.mark_as_used()
                await self.ctx.send("Deleted.")
        except asyncio.TimeoutError:
            pass

    def _check_react(self, reaction, user):
        assert reaction
        return user == self.ctx.author


class StaticForeign(Static):
    user_handler = ForeignUser
