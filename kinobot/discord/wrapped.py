import asyncio
import os
import tempfile

from discord import File

from kinobot.db import sql_to_dict
from kinobot.discord.extras.curator_user import Curator
from kinobot.discord.extras.verification import UserDB
from kinobot.misc import wrapped
from kinobot.utils import download_image

from .utils import call_with_typing


def _download_pp(user_id, url):
    path = os.path.join(tempfile.gettempdir(), f"wrapped_{user_id}")
    if os.path.exists(path):
        return path

    return download_image(url, path)


def make_wrapped(user_id, name="Unknown", profile_picture="", all_time=False):
    data = dict()

    data["name"] = name
    data["profile_picture"] = _download_pp(user_id, profile_picture)

    t_user = UserDB(user_id)
    data["tickets"] = len(t_user.available_tickets())

    curator_user = Curator(user_id)
    data["bytes"] = curator_user.size_left()
    curator_user.close()

    added_movies = sql_to_dict(
        None,
        wrapped.MOVIE_ADDITIONS_COUNT if not all_time else wrapped.MOVIE_ADDITIONS_ALL,
        (user_id,),
    )
    try:
        data.update(added_movies[0])
    except IndexError:
        pass

    stats = sql_to_dict(
        None,
        wrapped.POST_STATS_SQL if not all_time else wrapped.POST_STATS_SQL_ALL,
        (user_id,),
    )
    try:
        data.update(stats[0])
    except IndexError:
        pass

    data = {k: v for k, v in data.items() if v is not None}
    data["title"] = "#Wrapped" if all_time else None

    wrapped_ = wrapped.Wrapped.parse_obj(data)

    img = wrapped.make(wrapped_)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tf:
        img.save(tf.name)
        return tf.name


async def make(ctx, user_id, name, profile_picture, all_time=False):
    loop = asyncio.get_event_loop()
    img = await call_with_typing(
        ctx, loop, make_wrapped, user_id, name, profile_picture, all_time
    )
    with open(img, "rb") as file:
        await ctx.send(file=File(file, filename=os.path.basename(img)))

    try:
        os.remove(img)
    except:
        pass
