#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import asyncio
import datetime
import locale
import logging

from discord import File
from discord.ext import commands

from . import oldies
from ..config import settings
from ..constants import DISCORD_ANNOUNCER_WEBHOOK
from ..db import Execute
from ..exceptions import KinoException
from ..exceptions import KinoUnwantedException
from ..request import get_cls
from ..user import User
from ..utils import handle_general_exception
from ..utils import send_webhook
from .common import get_req_id_from_ctx
from .utils import IDLogger

_GOOD_BAD_NEUTRAL_EDIT = ("🇼", "🇱", "🧊", "✏️")
_ICE_DELAY = datetime.timedelta(days=1)


logger = logging.getLogger(__name__)


class OldiesChamber:
    "Class for the verification chamber used in the admin's Discord server."

    def __init__(
        self, bot: commands.Bot, ctx: commands.Context, tag=None, log_ids=True
    ):
        self._tag = tag
        self.bot = bot
        self.ctx = ctx
        self._log_ids = log_ids
        self._logger = IDLogger(settings.discord.logger, "ochamber")
        self._user_roles = [role.name for role in ctx.author.roles]
        self._user_id = str(ctx.author.id)  # type: ignore
        self._identifier = get_req_id_from_ctx(ctx)
        self._req_cls = get_cls(self._identifier)
        self._req = None
        self._seen_ids = set()
        self._images = []
        self._rejected = []
        self._verified = []
        self._iced = []
        self._edited = []

    async def _get_msg(self):
        try:
            message = await self.bot.wait_for(
                "message", timeout=300, check=self._check_msg(self.ctx.author)
            )
            return message
        except asyncio.TimeoutError:
            await self.ctx.send("Timeout!")
            return None

    async def _take_args(self):
        await self.ctx.send(
            f"[{self._tag}] Give the range of dates\nFormat: START_FROM, START_TO, END_FROM, END_TO\nExample: now, -1 year, now, -6 months"
        )
        user_msg = await self._get_msg()
        if user_msg is None:
            return None

        args = [a.strip() for a in str(user_msg.content).split(",")]
        if len(args) != 4:
            await self.ctx.send("Invalid format. Plesae read the instructions again.")
            return None

        return args

    async def start(self):
        "Start the chamber loop."
        args = await self._take_args()
        if not args:
            return await self.ctx.send("Bye.")

        await self.ctx.send("Give me the limit of requests (eg. 25)")
        msg = await self._get_msg()
        try:
            limit = int(msg.content.strip())
        except ValueError:
            return await self.ctx.send("Invalid integer limit")

        oldie = oldies.Repo.from_constants()

        self._oldies = oldie.get((args[0], args[1]), (args[2], args[3]), limit=limit)
        if not self._oldies:
            return await self.ctx.send("Nothing found")

        exc_count = 0

        for oldie in self._oldies:
            if exc_count > 10:
                await self.ctx.send("Exception count exceeded. Breaking loop.")
                break

            if not await self._loaded_req(oldie):
                exc_count += 1
                continue

            exc_count = 0

            await self._send_info()

            try:
                await self._verdict()
            except asyncio.TimeoutError:
                break

            if not await self._continue():
                break

        await self.ctx.send("Chamber loop finished")

        # self._send_webhook()

    async def _loaded_req(self, oldie) -> bool:
        """
        Load the request and the handler. Send the exception info if the
        handler fails.

        raises exceptions.NothingFound
        """
        self._req = self._req_cls.from_db_id(oldie.request_id)
        self._oldie = oldie

        if self._req.id in self._seen_ids:
            return False

        if self._log_ids:
            if self._logger.has_seen(self._req.id):
                return False

            self._logger.mark_as_seen(self._req.id)

        self._seen_ids.add(self._req.id)

        return await self._process_req()

    async def _handle_iced(self):
        assert self._req is not None

        ices = self._req.get_ices()

        if ices:
            logger.debug("Ices: %s", ices)
            if len(ices) > 5:
                await self.ctx.send(
                    f"`{self._req.comment}` has been already iced {len(ices)} times. Marking as used."
                )
                self._req.mark_as_used()
                return False

            last_ice = ices[-1]
            if last_ice["ago"] > _ICE_DELAY:
                await self.ctx.send(
                    f"Skipping recently iced request: {last_ice} ({len(ices)} ices) [Ice delay: {_ICE_DELAY}]"
                )
                return False
        else:
            logger.debug("This request doesn't have any ices registered")

        return True

    async def _process_req(self, raise_kino_exception=False):
        loop = asyncio.get_running_loop()

        async with self.ctx.typing():
            try:
                handler = await loop.run_in_executor(None, self._req.get_handler)
                self._images = await loop.run_in_executor(None, handler.get)
                risk = self._req.facebook_risk()

                if risk is not None:
                    await self.ctx.send(
                        f"WARNING: Facebook risk: `{risk}`.\n\nPLEASE BE CAREFUL! "
                        "DON'T GET THE PAGE BANNED!"
                    )

                return True

            except KinoUnwantedException as error:
                await self.ctx.send(self._format_exc(error))
                self._req.mark_as_used()

            except KinoException as error:
                await self.ctx.send(self._format_exc(error))

                if raise_kino_exception:
                    raise

                self._req.mark_as_used()

            except Exception as error:  # Fatal
                handle_general_exception(error)
                await self.ctx.send(
                    f"**Fatal!!!** {self._format_exc(error)}. "
                    "**Marking as used. REPORT ADMIN if you see this error too often!!!**"
                )

                self._req.mark_as_used()

            return False

    async def _send_info(self):
        "Send the request metadata and the images."
        user = User(id=self._req.user_id)
        user.load(register=True)

        message = None
        stats = f"impressions: **{_format_int(self._oldie.impressions)}**; engaged users: **{_format_int(self._oldie.engaged_users)}**"
        await self.ctx.send(
            f"**{user.name} ({self._req.time_ago})**: {self._req.pretty_title}\n\nStats: {stats}"
        )
        await self.ctx.send(f"{self._req.id}")

        for image in self._images:
            logger.info("Sending image: %s", image)
            message = await self.ctx.send(file=File(image))

        assert [await message.add_reaction(emoji) for emoji in _GOOD_BAD_NEUTRAL_EDIT]

    def _check_recurring_user(self):
        if self._verified.count(self._req.user.name) >= 2:
            logger.debug("%s has already two verified requests", self._req.user)
            return True

        return False

    async def _verdict(self):
        "raises asyncio.TimeoutError"
        await self.ctx.send(
            "You got 120 seconds to react to the last image. React "
            "with the ice cube to deal with the request later; react with "
            "the pencil to append flags to the request."
        )

        reaction, user = await self.bot.wait_for(
            "reaction_add", timeout=120, check=self._check_react
        )
        assert user

        if str(reaction) == str(_GOOD_BAD_NEUTRAL_EDIT[0]):
            if str(self._req.user.id) == self._user_id:
                await self.ctx.send("You can't verify your own request.")
            else:
                cloned = self._req.clone()
                self._req = cloned
                self._req.verify()

                if self._tag is not None:
                    self._req.add_tag(self._tag)

                self._log_user(verified=True)
                await self._take_reason(True)
                await self.ctx.send("Verified.")

        elif str(reaction) == str(_GOOD_BAD_NEUTRAL_EDIT[1]):
            # self._req.mark_as_used()
            # self._log_user()
            # await self._take_reason(False)
            await self.ctx.send("Marked as used.")

        elif str(reaction) == str(_GOOD_BAD_NEUTRAL_EDIT[3]):
            if not await self._edit_loop():
                await self.ctx.send("Ignored")
            else:
                await self._verdict()
        else:
            self._req.register_ice()
            self._log_user(iced=True)
            await self.ctx.send("Ignored.")

    async def _take_reason(self, verified: bool):
        self._req.register_verifications([self.ctx.author.id], verified, "automatic")

    def _check_msg_author(self, author):
        return lambda message: str(message.author.id) == str(self.ctx.author.id)

    def _check_msg(self, author):
        return lambda message: str(message.author.id) == str(self.ctx.author.id)

    async def _edit_loop(self):
        while True:
            edited = await self._edit_req()
            if not edited:
                await self.ctx.reply("Bad input.")
                return False

            # Send the request
            try:
                processed = await self._process_req(raise_kino_exception=True)
            except KinoException:
                continue
            else:
                if not processed:
                    return False
                else:
                    await self._send_info()
                    return True

    async def _edit_req(self):
        await self.ctx.send(
            "Type the flags you want to append. Type 'no' to cancel. "
            "Type 'reset' to remove all global flags set."
        )
        try:
            message = await self.bot.wait_for(
                "message", timeout=300, check=_check_msg_author(self.ctx.author)
            )

            if message.content.lower() == "no":
                return False

            if message.content.lower() == "reset":
                self._req.reset_global_flags()
                self._req.update()
                return True

            if self._req.edited:
                self._req.reset_append()

            self._req.append_text(str(message.content))

            return True

        except asyncio.TimeoutError:
            return False

    async def _continue(self) -> bool:
        queued = Execute().queued_requets(table=self._req_cls.table)
        message = await self.ctx.send(
            f"Continue in the chamber of {self._req_cls.table}? ({queued} verified)."
        )
        assert [
            await message.add_reaction(emoji) for emoji in _GOOD_BAD_NEUTRAL_EDIT[:2]
        ]

        try:
            reaction, user = await self.bot.wait_for(
                "reaction_add", timeout=30, check=self._check_react
            )
            assert user

            if str(reaction) == str(_GOOD_BAD_NEUTRAL_EDIT[0]):
                return True

            await self.ctx.send("Bye.")
            return False

        except asyncio.TimeoutError:
            await self.ctx.send("Timeout. Exiting...")
            return False

    def _check_react(self, reaction, user):
        assert reaction
        return user == self.ctx.author

    def _log_user(self, verified: bool = False, edited=False, iced=False):
        user = User(id=self._req.user_id)  # Temporary
        user.load(register=True)

        if iced:
            self._iced.append(user.name)
            return None

        if verified:
            self._verified.append(user.name)
        else:
            self._rejected.append(user.name)

        if edited:
            self._edited.append(user.name)

    def _verdict_author(self):
        return self.ctx.author.display_name

    def _send_webhook(self):
        msgs = [
            f"`{self._verdict_author()}` verdict for oldies chamber {self._identifier}:"
        ]

        if self._verified:
            msgs.append(
                f"Authors with **verified** requests: `{_user_str_list(self._verified)}`"
            )

        if self._rejected:
            msgs.append(
                f"Authors with **rejected** requests: `{_user_str_list(self._rejected)}`"
            )

        if self._iced:
            msgs.append(
                f"Authors with **iced (skipped)** requests: `{_user_str_list(self._iced)}`"
            )

        msgs.append(f"Total unique IDs: {self.unique_count}")

        if len(msgs) > 1:
            send_webhook(DISCORD_ANNOUNCER_WEBHOOK, "\n\n".join(msgs))

    @property
    def unique_count(self):
        return len(self._seen_ids)

    @staticmethod
    def _format_exc(error: Exception) -> str:
        return f"{type(error).__name__} raised: {error}"


class _FakeChamber(OldiesChamber):
    async def _process_req(self, raise_kino_exception=False):
        return True

    async def _send_info(self):
        message = await self.ctx.send("This is a fake request.")
        user = User(id=self._req.user_id)
        user.load(register=True)
        stats = f"impressions: **{_format_int(self._oldie.impressions)}**; engaged users: **{_format_int(self._oldie.engaged_users)}**"
        await self.ctx.send(
            f"**{user.name} ({self._req.time_ago})**: {self._req.pretty_title}\n\nStats: {stats}"
        )
        assert [await message.add_reaction(emoji) for emoji in _GOOD_BAD_NEUTRAL_EDIT]


# class OldiesChamber(_FakeChamber):
#    pass


def _user_str_list(user_list):
    user_list = {user: user_list.count(user) for user in user_list}
    user_list = {
        k: v
        for k, v in sorted(user_list.items(), key=lambda item: item[1], reverse=True)
    }
    str_list = [f"{key} ({val})" for key, val in user_list.items()]
    return ", ".join(str_list)
    # return ", ".join(list(dict.fromkeys(user_list)))


def _check_msg_author(author):
    return lambda message: message.author == author


locale.setlocale(locale.LC_ALL, "")


def _format_int(i):
    return format(i, ",d")
