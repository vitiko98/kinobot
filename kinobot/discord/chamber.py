#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import asyncio
import logging

from discord import File
from discord.ext import commands

from ..badge import Rejected
from ..constants import DISCORD_ANNOUNCER_WEBHOOK
from ..exceptions import KinoException, KinoUnwantedException
from ..request import Request
from ..user import User
from ..utils import send_webhook

_GOOD_BAD_NEUTRAL = ("👍", "💩", "🧊")


logger = logging.getLogger(__name__)


class Chamber:
    "Class for the verification chamber used in the admin's Discord server."

    def __init__(self, bot: commands.Bot, ctx: commands.Context, limit: int = 20):
        self.bot = bot
        self.ctx = ctx
        self.limit = limit
        self._req = None
        self._images = []
        self._rejected = []
        self._verified = []

    async def start(self):
        "Start the chamber loop."
        while True:
            if not await self._loaded_req():
                continue

            await self._send_info()

            try:
                await self._veredict()
            except asyncio.TimeoutError:
                break

            if not await self._continue():
                break

        self._send_webhook()

    async def _loaded_req(self) -> bool:
        """
        Load the request and the handler. Send the exception info if the
        handler fails.

        raises exceptions.NothingFound
        """
        self._req = Request.random_from_queue(verified=False)

        async with self.ctx.typing():
            try:
                handler = self._req.get_handler()
                self._images = handler.get()
                return True

            except KinoUnwantedException as error:
                await self.ctx.send(self._format_exc(error))

            except KinoException as error:
                await self.ctx.send(self._format_exc(error))
                self._req.mark_as_used()

            except Exception as error:  # Fatal
                await self.ctx.send(f"**Fatal!!!** {self._format_exc(error)}")

            return False

    async def _send_info(self):
        "Send the request metadata and the images."
        user = User(id=self._req.user_id)
        user.load(register=True)

        message = None
        await self.ctx.send(f"**{user.name}**: {self._req.pretty_title}")

        for image in self._images:
            logger.info("Sending image: %s", image)
            message = await self.ctx.send(file=File(image))

        assert [await message.add_reaction(emoji) for emoji in _GOOD_BAD_NEUTRAL]

    async def _veredict(self):
        "raises asyncio.TimeoutError"
        await self.ctx.send(
            "You got 45 seconds to react to the last image. React "
            "with the ice cube to deal with the request later."
        )

        reaction, user = await self.bot.wait_for(
            "reaction_add", timeout=45, check=self._check_react
        )
        assert user

        if str(reaction) == str(_GOOD_BAD_NEUTRAL[0]):
            self._req.verify()
            self._log_user(verified=True)
            await self.ctx.send("Verified.")

        elif str(reaction) == str(_GOOD_BAD_NEUTRAL[1]):
            self._req.mark_as_used()
            self._log_user()
            await self.ctx.send("Marked as used.")

        else:
            await self.ctx.send("Ignored.")

    async def _continue(self) -> bool:
        message = await self.ctx.send("Continue in the chamber?")
        assert [await message.add_reaction(emoji) for emoji in _GOOD_BAD_NEUTRAL[:2]]

        try:
            reaction, user = await self.bot.wait_for(
                "reaction_add", timeout=30, check=self._check_react
            )
            assert user

            if str(reaction) == str(_GOOD_BAD_NEUTRAL[0]):
                return True

            await self.ctx.send("Bye.")
            return False

        except asyncio.TimeoutError:
            await self.ctx.send("Timeout. Exiting...")
            return False

    def _check_react(self, reaction, user):
        assert reaction
        return user == self.ctx.author

    def _log_user(self, verified: bool = False):
        user = User(id=self._req.user_id)  # Temporary
        user.load(register=True)

        if verified:
            self._verified.append(user.name)
        else:
            badge = Rejected()
            badge.register(self._req.user.id, self._req.id)
            self._rejected.append(user.name)

    def _send_webhook(self):
        author = self.ctx.author.display_name  # type: ignore
        msgs = [f"`{author.title()}` veredict:"]

        if self._verified:
            users = ", ".join(list(dict.fromkeys(self._verified)))
            msgs.append(f"Authors with **verified** requests: `{users}`")

        if self._rejected:
            users = ", ".join(list(dict.fromkeys(self._rejected)))
            msgs.append(f"Authors that won **rejected** badges: `{users}`")

        if len(msgs) > 1:
            send_webhook(DISCORD_ANNOUNCER_WEBHOOK, "\n\n".join(msgs))

    @staticmethod
    def _format_exc(error: Exception) -> str:
        return f"{type(error).__name__} raised: {error}"
