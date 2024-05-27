import asyncio
from datetime import datetime
import logging
import sqlite3
from typing import Any, Callable, List, Optional

from discord.ext import commands

logger = logging.getLogger(__name__)


class ExitStatus(Exception):
    pass


def on_excs_send(excs, message="Command finished"):
    def decorator(func):
        async def wrapper(bot, ctx, *args, **kwargs):
            try:
                return await func(bot, ctx, *args, **kwargs)
            except excs as error:
                logger.exception(error)
                await ctx.send(message)

        return wrapper

    return decorator


async def call_with_typing(ctx, loop, *args):
    result = None
    async with ctx.typing():
        result = await loop.run_in_executor(None, *args)

    return result


def _slice_list(list_, n):
    groups = []
    for i in range(0, len(list_), n):
        groups.append(list_[i : i + n])

    return groups


def _check_author(author):
    return lambda message: message.author == author


async def ask(bot, ctx, timeout=120, custom_check=None, delete=False):
    try:
        msg = await bot.wait_for(
            "message", timeout=timeout, check=custom_check or _check_author(ctx.author)
        )
        if delete:
            await msg.delete()
            await ctx.send("Message deleted.", delete_after=10)

        return str(msg.content).strip()
    except asyncio.TimeoutError:
        return None


async def ask_to_confirm(
    bot,
    ctx,
    question="Are you sure? (y/n)",
    confirm_str="y",
    timeout=120,
    custom_check=None,
):
    await ctx.send(question)

    response = await ask(bot, ctx, timeout, custom_check)
    if response is None:
        return False

    return response.lower() == confirm_str


_PAG_HELP = f"Type the number of the item to pick; `n` to go to the next page; `p` to go the previous page; anything else to quit."


async def paginated_list(
    bot,
    ctx: commands.Context,
    header: str,
    items: List[Any],
    to_str_callback: Callable[[Any], str] = lambda l: str(l),
    slice_in=20,
    timeout=60,
) -> Optional[Any]:
    if not items:
        logger.debug("No items to generate.")
        return None

    str_items = [f"{n}. {to_str_callback(i)}" for n, i in enumerate(items, start=1)]
    lists = _slice_list(str_items, slice_in)
    requested_index = 0

    max_index = len(lists) - 1
    strs = "\n".join(lists[requested_index])
    message = await ctx.send(f"{header} (page 1/{max_index+1}). {_PAG_HELP}\n{strs}")

    while True:
        response = await ask(bot, ctx, timeout=timeout)

        if response is None:
            break

        if response not in ("b", "n"):
            try:
                return items[int(response) - 1]
            except (ValueError, IndexError):
                await ctx.send("Invalid index. Bye.")
                return None

        should_change = False
        if response == "p":
            if requested_index > 0:
                requested_index -= 1
                should_change = True

        elif response == "n":
            if requested_index < max_index:
                requested_index += 1
                should_change = True

        if should_change:
            strs = "\n".join(lists[requested_index])
            await message.edit(
                content=f"{header} (page {requested_index+1}/{max_index+1}), {_PAG_HELP}\n{strs}"
            )


class IDLogger:
    def __init__(self, db_name, table_name="seen_ids"):
        self._db_name = db_name
        self._table_name = table_name
        self._conn = sqlite3.connect(db_name)
        self._create_table()

    def _create_table(self):
        with self._conn:
            self._conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {self._table_name}
                                 (id CHAR PRIMARY KEY,
                                  seen_at TIMESTAMP)"""
            )

    def mark_as_seen(self, id, seen_at=None):
        if seen_at is None:
            seen_at = datetime.now()
        with self._conn:
            self._conn.execute(
                f"INSERT INTO {self._table_name} (id, seen_at) VALUES (?, ?)",
                (id, seen_at),
            )

    def has_seen(self, id, within_last=None):
        if within_last is None:
            with self._conn:
                cursor = self._conn.execute(
                    f"SELECT id FROM {self._table_name} WHERE id=?", (id,)
                )
                return cursor.fetchone() is not None
        else:
            since = datetime.now() - within_last
            with self._conn:
                cursor = self._conn.execute(
                    f"SELECT id FROM {self._table_name} WHERE id=? AND seen_at >= ?",
                    (id, since),
                )
                return cursor.fetchone() is not None

    def __str__(self) -> str:
        return f"<IDLogger {self._table_name}@{self._db_name}>"
