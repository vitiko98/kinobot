#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import asyncio
import logging


from discord import File
from discord.ext import commands
from .common import get_req_id_from_ctx

from ..constants import DISCORD_ANNOUNCER_WEBHOOK
from ..db import Execute
from ..exceptions import KinoException, KinoUnwantedException
from ..request import get_cls
from ..user import User
from ..utils import handle_general_exception, send_webhook

_GOOD_BAD_NEUTRAL_EDIT = ("🇼", "🇱", "🧊", "✏️")


logger = logging.getLogger(__name__)


class Chamber:
    "Class for the verification chamber used in the admin's Discord server."

    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self.ctx = ctx
        self._user_id = str(ctx.author.id)  # type: ignore
        self._identifier = get_req_id_from_ctx(ctx)
        self._req_cls = get_cls(self._identifier)
        self._req = None
        self._seen_ids = set()
        self._images = []
        self._rejected = []
        self._verified = []
        self._edited = []

        logger.debug("Req class: %s", self._req_cls)

    async def start(self):
        "Start the chamber loop."
        exc_count = 0

        while True:
            if exc_count > 3:
                await self.ctx.send("Exception count exceeded. Breaking loop.")
                break

            if not await self._loaded_req():
                exc_count += 1
                continue

            exc_count = 0

            await self._send_info()

            try:
                await self._veredict()
            except asyncio.TimeoutError:
                break

            if not await self._continue():
                break

        await self.ctx.send("Chamber loop finished")

        self._send_webhook()

    async def _loaded_req(self) -> bool:
        """
        Load the request and the handler. Send the exception info if the
        handler fails.

        raises exceptions.NothingFound
        """
        self._req = self._req_cls.random_from_queue(verified=False)

        if self._req.id in self._seen_ids:
            return False

        self._seen_ids.add(self._req.id)

        if self._req.find_dupe(verified=True):
            await self.ctx.send(f"Ignoring potential dupe post: {self._req.comment}")
            return False

        return await self._process_req()

    async def _process_req(self, raise_kino_exception=False):
        loop = asyncio.get_running_loop()

        async with self.ctx.typing():
            try:
                handler = await loop.run_in_executor(None, self._req.get_handler)
                self._images = await loop.run_in_executor(None, handler.get)
                return True

            except KinoUnwantedException as error:
                await self.ctx.send(self._format_exc(error))

            except KinoException as error:
                await self.ctx.send(self._format_exc(error))

                if raise_kino_exception:
                    raise

                self._req.mark_as_used()

            except Exception as error:  # Fatal
                handle_general_exception(error)
                await self.ctx.send(f"**Fatal!!!** {self._format_exc(error)}")

            return False

    async def _send_info(self):
        "Send the request metadata and the images."
        user = User(id=self._req.user_id)
        user.load(register=True)

        message = None
        await self.ctx.send(
            f"**{user.name} ({self._req.time_ago})**: {self._req.pretty_title}"
        )

        for image in self._images:
            logger.info("Sending image: %s", image)
            message = await self.ctx.send(file=File(image))

        assert [await message.add_reaction(emoji) for emoji in _GOOD_BAD_NEUTRAL_EDIT]

    async def _veredict(self):
        "raises asyncio.TimeoutError"
        await self.ctx.send(
            "You got 45 seconds to react to the last image. React "
            "with the ice cube to deal with the request later; react with "
            "the pencil to append flags to the request."
        )

        reaction, user = await self.bot.wait_for(
            "reaction_add", timeout=45, check=self._check_react
        )
        assert user

        if str(reaction) == str(_GOOD_BAD_NEUTRAL_EDIT[0]):
            if str(self._req.user.id) == self._user_id:
                await self.ctx.send("You can't verify your own request.")
            else:
                self._req.verify()
                self._log_user(verified=True)
                self._req.register_verifications(
                    [str(self.ctx.author.id)], True, "Botmin verified this"
                )
                await self.ctx.send("Verified.")

        elif str(reaction) == str(_GOOD_BAD_NEUTRAL_EDIT[1]):
            self._req.mark_as_used()
            self._log_user()
            self._req.register_verifications(
                [str(self.ctx.author.id)], False, "Botmin rejected this"
            )
            await self.ctx.send("Marked as used.")

        elif str(reaction) == str(_GOOD_BAD_NEUTRAL_EDIT[3]):
            if not await self._edit_loop():
                await self.ctx.send("Ignored")
            else:
                await self._veredict()
        else:
            await self.ctx.send("Ignored.")

    async def _edit_loop(self):
        while True:
            edited = await self._edit_req()
            if not edited:
                await self.ctx.reply("Fucking idiot.")
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
        await self.ctx.send("Type the flags you want to append. Type 'no' to cancel.")
        try:
            message = await self.bot.wait_for(
                "message", timeout=300, check=_check_msg_author(self.ctx.author)
            )

            if message.content.lower() == "no":
                return False

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

    def _log_user(self, verified: bool = False, edited=False):
        user = User(id=self._req.user_id)  # Temporary
        user.load(register=True)

        if verified:
            self._verified.append(user.name)
        else:
            self._rejected.append(user.name)

        if edited:
            self._edited.append(user.name)

    def _veredict_author(self):
        return self.ctx.author.display_name

    def _send_webhook(self):
        msgs = [f"`{self._veredict_author()}` veredict for {self._identifier}:"]

        if self._verified:
            msgs.append(
                f"Authors with **verified** requests: `{_user_str_list(self._verified)}`"
            )

        if self._rejected:
            msgs.append(
                f"Authors with **rejected** badges and requests: `{_user_str_list(self._rejected)}`"
            )

        if self._edited:
            msgs.append(
                f"Authors with **edited** badges and requests: `{_user_str_list(self._edited)}`"
            )

        if len(msgs) > 1:
            send_webhook(DISCORD_ANNOUNCER_WEBHOOK, "\n".join(msgs))

    @staticmethod
    def _format_exc(error: Exception) -> str:
        return f"{type(error).__name__} raised: {error}"


class _FakeChamber(Chamber):
    async def _process_req(self, raise_kino_exception=False):
        return True

    async def _send_info(self):
        message = await self.ctx.send("This is a fake request.")
        assert [await message.add_reaction(emoji) for emoji in _GOOD_BAD_NEUTRAL_EDIT]


class CollaborativeChamber(Chamber):
    def __init__(self, bot, ctx, members):
        super().__init__(bot, ctx)
        self._members = members
        self._first_req = True

    @classmethod
    async def from_bot(cls, bot, ctx, partners, roles=("verifier", "botmin")):
        if not partners:
            raise KinoException(
                f"You need to tag at least one verifier partner (e.g. !chamber @dummy @dummy_2)"
            )

        members = [ctx.author]

        for partner in partners:
            partner = partner.strip()

            if not partner.startswith("<@"):
                raise KinoException(f"Invalid partner: {partner}")

            id_ = partner.lstrip("<@").rstrip(">")

            member = await ctx.message.guild.fetch_member(id_)

            if not any(str(role.name) in roles for role in member.roles):
                raise KinoException(f"{partner} isn't allowed to enter the chamber")

            if str(member.id) in (str(mem.id) for mem in members):
                raise KinoException(f"You can't add duplicate verifiers.")

            members.append(member)

        return cls(bot, ctx, members)

    async def _loaded_req(self) -> bool:
        self._req = self._req_cls.random_from_queue(verified=False)

        self._req.user.load()

        if self._req.id in self._seen_ids:
            return False

        self._seen_ids.add(self._req.id)

        if str(self._req.user.id) in self._member_ids():
            await self.ctx.send(
                f"Ignoring **{self._req.pretty_title}** as the author is in the chamber."
            )
            return False

        if self._req.find_dupe(verified=True):
            await self.ctx.send(
                f"Ignoring potential dupe post: **{self._req.comment}**"
            )
            return False

        return await self._process_req()

    async def _continue(self) -> bool:
        queued = Execute().queued_requets(table=self._req_cls.table)
        message = await self.ctx.send(
            f"{self._mentions_str()} Continue in the chamber of {self._req_cls.table}? "
            f"({queued} verified). Absolute majority!"
        )
        assert [
            await message.add_reaction(emoji) for emoji in _GOOD_BAD_NEUTRAL_EDIT[:2]
        ]

        collected_reacts = await self._collect_reacts()

        min_ = len(self._members) / 2
        return collected_reacts.count(_GOOD_BAD_NEUTRAL_EDIT[0]) > min_

    async def _collect_reacts(self, timeout=180):
        collected_reacts = []
        user_ids = set()

        while True:
            try:
                reaction, user = await self.bot.wait_for(
                    "reaction_add", timeout=timeout, check=self._check_react
                )

                if str(user.id) in user_ids:
                    continue

                user_ids.add(str(user.id))
                collected_reacts.append(str(reaction))

                if len(collected_reacts) >= len(self._members):
                    return collected_reacts

            except asyncio.TimeoutError:
                await self.ctx.send("Timeout!")
                return []

    async def _veredict(self):
        if self._first_req:
            await self.ctx.send(
                f"{self._mentions_str()} you got 3 minutes to react to the last image. React "
                "with the ice cube to deal with the request later; react with "
                "the pencil to append flags to the request. Absolute majority!"
            )
            self._first_req = False
        else:
            await self.ctx.send(
                f"{self._mentions_str()} you got 3 minutes to react to the last image."
            )

        collected_reacts = await self._collect_reacts()

        min_ = len(self._members) / 2

        verified = collected_reacts.count(_GOOD_BAD_NEUTRAL_EDIT[0]) > min_
        rejected = collected_reacts.count(_GOOD_BAD_NEUTRAL_EDIT[1]) > min_
        to_edit = collected_reacts.count(_GOOD_BAD_NEUTRAL_EDIT[3]) > min_

        if verified:
            self._req.verify()
            self._log_user(verified=True)
            await self._take_reason(True)
            await self.ctx.send("Verified.")

        elif rejected:
            self._req.mark_as_used()
            self._log_user()
            await self._take_reason(False)
            await self.ctx.send("Marked as used.")

        elif to_edit:
            if not await self._edit_loop():
                await self.ctx.send("Ignored")
            else:
                await self._veredict()
        else:
            await self.ctx.send("Ignored.")

    async def _edit_req(self):
        await self.ctx.send(
            "Type the flags to append. Type 'no' to cancel. "
            "(The bot will take the FIRST MESSAGE)."
        )
        try:
            message = await self.bot.wait_for(
                "message", timeout=300, check=self._check_msg_author(self.ctx.author)
            )

            if message.content.lower() == "no":
                return False

            if self._req.edited:
                self._req.reset_append()

            self._req.append_text(str(message.content))

            return True

        except asyncio.TimeoutError:
            return False

    async def _take_reason(self, verified: bool):
        await self.ctx.send(
            "Please explain shortly why:\n"
            "(The bot will take the FIRST MESSAGE PREFIXED WITH 'bc' or 'because')."
        )
        try:
            message = await self.bot.wait_for(
                "message", timeout=300, check=self._check_reason_msg(self.ctx.author)
            )
            reason = str(message.content).lstrip("bc").lstrip("because")
            self._req.register_verifications(self._member_ids(), verified, reason)

            return True

        except asyncio.TimeoutError:
            return False

    def _check_react(self, reaction, user):
        return (
            str(user.id) in self._member_ids()
            and str(reaction) in _GOOD_BAD_NEUTRAL_EDIT
        )

    def _check_msg_author(self, author):
        return lambda message: str(message.author.id) in self._member_ids()

    def _check_reason_msg(self, author):
        return (
            lambda message: str(message.content).startswith(("bc", "because"))
            and str(message.author.id) in self._member_ids()
        )

    def _member_ids(self):
        return (str(member.id) for member in self._members)

    def _mentions_str(self):
        return " ".join(f"<@{member.id}>" for member in self._members)

    def _veredict_author(self):
        return ", ".join(member.display_name for member in self._members)


def _user_str_list(user_list):
    return ", ".join(list(dict.fromkeys(user_list)))


def _check_msg_author(author):
    return lambda message: message.author == author
