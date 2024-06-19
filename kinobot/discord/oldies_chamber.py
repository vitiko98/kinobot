#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko <vhnz98@gmail.com>

import asyncio
import datetime
import locale
import logging
from typing import Dict

from discord import File
from discord.ext import commands

from . import oldies
from ..db import Execute
from ..db import sql_to_dict
from ..exceptions import KinoException
from ..exceptions import KinoUnwantedException
from ..exceptions import MovieNotFound
from ..exceptions import TempUnavailable
from ..media import Movie
from ..request import get_cls
from ..user import User
from ..utils import handle_general_exception
from ..utils import send_webhook
from .common import get_req_id_from_ctx

_GOOD_BAD_NEUTRAL_EDIT = ("🇼", "🇱", "🧊", "✏️")
_ICE_DELAY = datetime.timedelta(days=1)


logger = logging.getLogger(__name__)


def _custom_movie(req_cls, query, *args, **kwargs):
    sql1 = (
        "select movies.id as id from movies join movie_credits on movie_credits.movie_id == movies.id "
        "join people on people.id=movie_credits.people_id where people.name like ? group by movies.id"
    )
    ids = [i["id"] for i in sql_to_dict(None, sql1, (f"%{query}%",))]

    try:
        movie = Movie.from_query(query)
    except Exception as error:
        if not ids:
            raise
    else:
        ids.append(str(movie.id))

    if not ids:
        raise MovieNotFound

    marks = ("?," * len(ids)).rstrip(",")

    sql = (
        "select requests.id as request_id, posts.engaged_users as engaged from requests left join posts"
        " on posts.request_id=requests.id left join movie_posts on movie_posts.post_id=posts.id "
        f"where movie_posts.movie_id in ({marks}) order by posts.engaged_users desc"
    )
    return sql_to_dict(None, sql, tuple(ids))


def _log(req_id):
    Execute()._execute_sql("insert into chamber_log (request_id) values (?)", (req_id,))


def _is_available(req_id):
    items = sql_to_dict(None, "select * from chamber_log where request_id=?", (req_id,))
    if items:
        return False

    return True


def _older(*args):
    # fixme
    msg = "[{self._tag}] Give the range of dates\nFormat: START_FROM, START_TO, END_FROM, END_TO\nExample: now, -1 year, now, -6 months"
    args = [a.strip() for a in str(msg.content).split(",")]


_FACTORIES = {"custom_movie": _custom_movie}


class OldiesChamber:
    "Class for the verification chamber used in the admin's Discord server."

    def __init__(
        self,
        bot: commands.Bot,
        ctx: commands.Context,
        tag=None,
        request_factory="custom_movie",
    ):
        self._tag = tag
        self.bot = bot
        self.ctx = ctx
        self._request_factory = request_factory
        self._factory = _FACTORIES[request_factory]
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

        logger.debug("Req class: %s", self._req_cls)

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
            f"[{self._tag}] [{self._request_factory}] Give me the query for this factory."
        )
        user_msg = await self._get_msg()
        if user_msg is None:
            return None

        return str(user_msg.content).strip()

    async def start(self):
        "Start the chamber loop."
        args = await self._take_args()
        if not args:
            return await self.ctx.send("Bye.")

        self._items = self._factory(self._req_cls, args)
        if not self._items:
            return await self.ctx.send("Nothing found.")

        exc_count = 0

        for item in self._items:
            if exc_count > 10:
                await self.ctx.send("Exception count exceeded. Breaking loop.")
                break

            if not await self._loaded_req(item):
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

    async def _loaded_req(self, item: Dict) -> bool:
        """
        Load the request and the handler. Send the exception info if the
        handler fails.

        raises exceptions.NothingFound
        """
        self._req = self._req_cls.from_db_id(item["request_id"])
        self._metadata = item

        if str(self._req.user.id) == self._user_id:
            logger.debug("Ignoring own request")
            return False

        if _is_available(self._req.id) is False:
            logger.debug("Request was already logged")
            return False

        if self._req.id in self._seen_ids:
            return False

        _log(self._req.id)
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

            except TempUnavailable:
                await self.ctx.send("TempUnavailable")

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
        metadata = f"metadata: {self._metadata}"
        await self.ctx.send(
            f"**{user.name} ({self._req.time_ago})**: {self._req.pretty_title}\n\n{metadata}"
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
            pass
            # send_webhook(DISCORD_ANNOUNCER_WEBHOOK, "\n\n".join(msgs))

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
        await self.ctx.send(
            f"**{user.name} ({self._req.time_ago})**: {self._req.pretty_title}\n\nMetadata: {self._metadata}"
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
