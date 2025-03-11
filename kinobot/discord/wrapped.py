import asyncio
import requests
import hashlib
import logging
import os
import tempfile

from discord import File

from kinobot.db import sql_to_dict
from kinobot.discord.extras.curator_user import Curator
from kinobot.discord.extras.verification import UserDB
from kinobot.misc import wrapped, poster
from kinobot.utils import download_image

from .utils import call_with_typing


logger = logging.getLogger(__name__)


class NoData(Exception):
    pass


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
        ctx, loop, make_wrapped_2, user_id, name, profile_picture, all_time
    )
    with open(img, "rb") as file:
        await ctx.send(file=File(file, filename=os.path.basename(img)))

    try:
        os.remove(img)
    except:
        pass


# 2024
SQL_TOP_MOVIE = """SELECT
    m.id AS id,
    m.title AS title, m.poster as poster,
    COUNT(p.id) AS post_count
FROM
    users u
JOIN
    requests r ON u.id = r.user_id
JOIN
    posts p ON r.id = p.request_id
JOIN
    movie_posts mp ON p.id = mp.post_id
JOIN
    movies m ON mp.movie_id = m.id
WHERE
    u.id = ?
    AND strftime('%Y', p.added) = '2024'
    AND r.comment NOT LIKE '%!swap%'
GROUP BY
    m.id, m.title
ORDER BY
    post_count DESC"""

# AND strftime('%Y', p.added) = strftime('%Y', 'now')

SQL_TOP_TV = """ SELECT
    ts.id AS id,
    ts.name AS title, ts.poster_path as poster,
    COUNT(p.id) AS post_count
FROM
    users u
JOIN
    requests r ON u.id = r.user_id
JOIN
    posts p ON r.id = p.request_id
JOIN
    episode_posts ep ON p.id = ep.post_id
JOIN
    episodes e ON ep.episode_id = e.id
JOIN
    tv_shows ts ON e.tv_show_id = ts.id
WHERE
    u.id = ?
    AND strftime('%Y', p.added) = '2024'
    AND r.comment NOT LIKE '%!swap%'
GROUP BY
    ts.id
ORDER BY
    post_count DESC"""

IMG_BASE = "https://image.tmdb.org/t/p/original"


def _get_posters(items):
    posters = []
    for item in items:
        if not item["poster"]:
            continue

        if not item["poster"].startswith("https"):
            poster_path = IMG_BASE + item["poster"]
        else:
            poster_path = item["poster"]

        posters.append(poster_path)

    return posters


def _download_image(url, cache_dir="/tmp", retries=2):
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    file_name = hashlib.md5(url.encode()).hexdigest() + ".jpg"
    file_path = os.path.join(cache_dir, file_name)
    failed_marker = os.path.join(cache_dir, file_name + ".failed")

    if os.path.exists(failed_marker):
        logger.debug(f"Image has failed previously, skipping: {url}")
        return None

    if os.path.exists(file_path):
        logger.debug(f"Image already cached: {file_path}")
        return file_path

    for attempt in range(retries + 1):
        try:
            logger.debug(f"Downloading {url}, Attempt {attempt + 1}")
            response = requests.get(url, stream=True)
            response.raise_for_status()

            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.debug(f"Image downloaded and cached at: {file_path}")
            return file_path

        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading the image on attempt {attempt + 1}: {e}")
            if attempt == retries:
                with open(failed_marker, "w") as f:
                    f.write("failed\n")
                logger.error(
                    f"Image failed to download after {retries + 1} attempts: {url}"
                )

    return None


def _get_top_media(user_id):
    movies = sql_to_dict(None, SQL_TOP_MOVIE, (user_id,))
    tv_shows = sql_to_dict(None, SQL_TOP_TV, (user_id,))

    sorted_combined_list = sorted(
        movies + tv_shows, key=lambda x: x["post_count"], reverse=True
    )

    posters = _get_posters(sorted_combined_list)
    finished = []
    for poster in posters[:6]:
        path = _download_image(poster, "/tmp")
        finished.append(path)

    try:
        top_movie = movies[0]["title"]
    except:
        top_movie = "N/A"

    try:
        top_tv_show = tv_shows[0]["title"]
    except:
        top_tv_show = "N/A"

    return dict(poster_paths=finished, top_movie=top_movie, top_tv_show=top_tv_show)


def _truncate_title(title, max_length=19):
    if len(title) > max_length:
        return title[: max_length - 3] + "..."

    return title


def make_wrapped_2(user_id, name="Unknown", profile_picture="", all_time=False):
    data = dict()

    data["name"] = name

    t_user = UserDB(user_id)
    data["tickets"] = len(t_user.available_tickets())

    curator_user = Curator(user_id)
    data["bytes"] = curator_user.size_left()
    curator_user.close()

    stats = sql_to_dict(
        None,
        wrapped.POST_STATS_SQL if not all_time else wrapped.POST_STATS_SQL_ALL,
        (user_id,),
    )
    try:
        data.update(stats[0])
    except IndexError:
        pass

    try:
        top_media = _get_top_media(user_id)
    except Exception as error:
        logger.exception(error)
        raise NoData("No media data") from error

    poster_d = poster.KinoReview(
        header=data["name"],
        sub_header="Kino'24",
        poster_paths=list(top_media["poster_paths"]),
        title="2024",
        place_1=(_truncate_title(top_media["top_movie"]), "Top Posted Movie"),
        place_2=(_truncate_title(top_media["top_tv_show"]), "Top Posted Series"),
        place_3=(poster.format_number(data["views"]), "Views"),
        place_4=(poster.format_number(data["total_posts"]), "Total Posts"),
        place_5=(poster.format_bytes(data["bytes"]), "Buffer"),
        place_6=(poster.format_number(data["tickets"]), "Tickets"),
    )

    try:
        img = poster.make(poster_d)
    except ZeroDivisionError:
        raise NoData

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tf:
        img.save(tf.name)
        return tf.name
