from contextlib import contextmanager
from typing import Any
from kinobot.infra import misc
from kinobot.request import VideoRequest
import logging
import asyncio
from discord import File
import os
from .utils import call_with_typing
import tempfile

from kinobot.sources import video
from discord.ext import commands

logger = logging.getLogger(__name__)


def _is_file_too_large(file_path, max_size_mb=8):
    max_size_bytes = max_size_mb * 1024 * 1024
    return os.path.getsize(file_path) > max_size_bytes


async def make(ctx: commands.Context, args):
    def _make():
        req = VideoRequest.from_discord(args, ctx)  # type: VideoRequest
        no_subs = req.args.get("no_subs", False)
        data = req.compute()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".srt", mode="w") as tf:
            to_write = video.make_subs(data)
            tf.writelines(to_write)

        if not to_write or no_subs:
            subtitle_file = None
        else:
            subtitle_file = tf.name

        multiple = len(data) > 1

        clips = []
        for d in data:
            instance = video.ClipExtractor(d["path"])

            if multiple:
                subtitle_input = None
            else:
                subtitle_input = subtitle_file

            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tf:
                instance.extract_clip(
                    d["start_ms"], d["end_ms"], tf.name, subtitle_file=subtitle_input
                )
                if _is_file_too_large(tf.name):
                    raise ValueError("File is too large")

                clips.append(tf.name)

        def remove_subs():
            if subtitle_file is not None:
                try:
                    os.remove(subtitle_file)
                except:
                    pass

        if len(clips) < 2:
            remove_subs()
            return clips[0]

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tf:
            video.concatenate_videos(clips, tf.name, subtitle_file=subtitle_file)

            for clip in clips:
                try:
                    os.remove(clip)
                except:
                    pass

            remove_subs()
            return tf.name

    loop = asyncio.get_event_loop()

    result = await call_with_typing(ctx, loop, _make)
    try:
        await ctx.send("Here is your video! 🎥")
        await ctx.send(file=File(result))
    except Exception as e:
        logger.error(e)
        await ctx.send(f"Failed to upload video: {e}")
    finally:
        os.remove(result)


class NoBalance(Exception):
    pass


async def give_tokens(ctx: commands.Context, user: Any, amount: int):
    misc.add_token_transaction(user.id, amount, "CREDIT")
    balance = misc.get_user_token_balance(user.id)
    msg = f"Credit of {amount} video tokens. New balance: {balance}"
    await ctx.send(msg)


async def remove_tokens(ctx: commands.Context, user: Any, amount: int):
    misc.add_token_transaction(user.id, amount, "DEBIT")
    balance = misc.get_user_token_balance(user.id)
    msg = f"DEBIT of {amount} video tokens. New balance: {balance}"
    await ctx.send(msg)


async def get_balance(ctx: commands.Context, user: Any):
    balance = misc.get_user_token_balance(user.id)
    await ctx.send(f"Your token balance is **{balance}**")


@contextmanager
def deduct_token(user_id):
    balance = misc.get_user_token_balance(user_id)
    if balance < 1:
        raise NoBalance("Insufficient balance to deduct credit.")

    misc.add_token_transaction(user_id, 1, "DEBIT", "Default")

    yield balance
