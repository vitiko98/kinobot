import asyncio
import json
import os
import tempfile
import datetime
import logging

from typing import Literal, Optional

from discord import Embed, File
from discord.ext import commands
from pydantic import BaseModel, Field, ValidationError
from kinobot.misc import emby
from kinobot.infra import misc
from kinobot.config import config
from kinobot.misc.poster import create_video_from_images
from kinobot.utils import get_args_and_clean


from .utils import ask
from .utils import ask_to_confirm
from .utils import call_with_typing
from .utils import paginated_list


logger = logging.getLogger(__name__)


def _calculate_timezone_from_hour(input_hour_str):
    try:
        input_hour = int(input_hour_str)

        now = datetime.datetime.now().astimezone()
        system_hour = now.hour

        offset_hours = input_hour - system_hour

        if offset_hours > 12:
            offset_hours -= 24
        elif offset_hours < -12:
            offset_hours += 24

        return offset_hours

    except ValueError:
        raise ValueError(
            "Invalid input. Please provide a valid hour as a string (e.g., '10')."
        )


async def setup(bot, ctx: commands.Context):
    await ctx.send("Give me your Emby username. Type 'n' if you don't use it")
    emby_username = await ask(bot, ctx, none_if="n")

    await ctx.send("Give me your Jellyfin username. Type 'n' if you don't use it")
    jellyfin_username = await ask(bot, ctx, none_if="n")

    await ctx.send(
        "Tell me the current hour of your clock (0-24 format). This will be used to calculate your timezone."
    )
    current_hour = await ask(bot, ctx) or "0"
    offset = _calculate_timezone_from_hour(current_hour)

    model = misc.UserEmbyData(
        timezone_offset=offset,
        jellyfin_username=jellyfin_username,
        emby_username=emby_username,
        user_id=ctx.author.id,
    )
    misc.update_or_create_emby_data(model)
    await ctx.send(f"Setup complete: {model}")


def _make_emby():
    return emby.Client(config.emby.host, config.emby.api_key)


def _make_jellyfin():
    return emby.Client(
        config.jellyfin.host, config.jellyfin.api_key, factory="jellyfin"
    )


def _make(
    data_model,
    username,
    backdrops=False,
    period_key="month",
    type="movie",
    emby_username=None,
    jellyfin_username=None,
    multiple=False,
):
    jellyfin_username_default = data_model.jellyfin_username
    emby_username_default = data_model.emby_username
    if emby_username is not None:
        jellyfin_username_default = None
        emby_username_default = emby_username

    if jellyfin_username is not None:
        emby_username_default = None
        jellyfin_username_default = jellyfin_username

    return emby.make(
        _make_emby(),
        _make_jellyfin(),
        emby_username_default,
        jellyfin_username_default,
        username,
        backdrops=backdrops,
        period_key=period_key,
        multiple=multiple,
        type=type,
    )


class LastPlayedArgs(BaseModel):
    period: Literal["month", "week", "3month", "year", "day", "all"] = "month"
    backdrops: bool = False
    type: Literal["movie", "series", "all"] = "movie"
    emby_user: Optional[str] = None
    jellyfin_user: Optional[str] = None
    video: bool = False

    @classmethod
    def parse(cls, str_: str):
        _, data = get_args_and_clean(
            str_,
            args=(
                "--period",
                "--backdrops",
                "--type",
                "--emby-user",
                "--jellyfin-user",
                "--video",
            ),
        )
        return cls.model_validate(data)


async def run(bot, ctx: commands.Context, content: str):
    data_model = misc.get_emby_data(ctx.author.id)
    if not data_model:
        return await ctx.send(
            "No data found for your user. Setup your data running !emsetup"
        )

    try:
        config = LastPlayedArgs.parse(f"dummy {content}")
    except ValidationError as error:
        error_data = json.loads(error.json())[0]
        msg = error_data["msg"]
        loc = error_data["loc"]
        return await ctx.send(
            f"{loc}: {msg}" + "\n\nUsage:\n"
            "!lastplayed [--period {month,week,3month,year,day,all}] [--backdrops] [--type {movie,series,all}]"
        )

    def _run():
        username_title = (
            config.emby_user
            or config.jellyfin_user
            or data_model.emby_username
            or data_model.jellyfin_username
        )
        result = _make(
            data_model,
            username_title,
            config.backdrops,
            period_key=config.period,
            type=config.type,
            emby_username=config.emby_user,
            jellyfin_username=config.jellyfin_user,
            multiple=config.video,
        )
        if isinstance(result, list):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tf:
                create_video_from_images(result, tf.name)
                return tf.name
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tf:
                result.save(tf.name)
                return tf.name

    loop = asyncio.get_event_loop()
    result = await call_with_typing(ctx, loop, _run)

    with open(result, "rb") as file:
        await ctx.send(file=File(file, filename=os.path.basename(result)))

    os.remove(result)
