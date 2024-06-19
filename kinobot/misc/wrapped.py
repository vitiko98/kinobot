import datetime
from typing import Optional

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from pydantic import BaseModel

from kinobot.config import settings


def _format_number(num):
    abbreviations = [(1e9, "B"), (1e6, "M"), (1e3, "K")]

    for factor, suffix in abbreviations:
        if num <= 1e6 and num >= 1e3:
            return f"{int(num / 1e3)}K"

        if num >= factor:
            formatted_num = num / factor
            return f"{formatted_num:.1f}{suffix}"

    return str(num)


def _format_bytes(num):
    if num <= 0:
        num = 0

    abbreviations = [(1e12, "TBs"), (1e9, "GBs"), (1e6, "MBs"), (1e3, "KBs")]

    for factor, suffix in abbreviations:
        if num >= factor:
            formatted_num = num / factor
            formatted_num = f"{formatted_num:.1f}"

            if formatted_num.endswith("0"):
                formatted_num = str(int(num / factor))

            return {"title": formatted_num, "subtitle": suffix}

    return {"title": str(num), "subtitle": "Bytes"}


class Wrapped(BaseModel):
    name: str = "Unknown"
    profile_picture: str
    total_posts: int = 0
    views: int = 0
    engaged_users: int = 0
    shares: int = 0
    bytes: int = 0
    tickets: int = 0
    added_movies: int = 0
    title: Optional[str] = None


def _center_crop(image):
    width, height = image.size
    crop_size = min(width, height)
    left = (width - crop_size) / 2
    top = (height - crop_size) / 2
    right = (width + crop_size) / 2
    bottom = (height + crop_size) / 2
    cropped_image = image.crop((left, top, right, bottom))
    return cropped_image


CIRCULAR_MEDIUM = settings.wrapped.font_medium
CIRCULAR_BOLD = settings.wrapped.font_bold

FONT_COLOR = settings.wrapped.font_color
TEMPLATE = settings.wrapped.template


POST_STATS_SQL = "select sum(posts.shares) as shares, sum(posts.impressions) as views, sum(posts.engaged_users) as engaged_users, count(posts.id) as total_posts from posts inner join requests on posts.request_id=requests.id where requests.user_id=? AND strftime('%Y', posts.added) = strftime('%Y', 'now')"
POST_STATS_SQL_ALL = "select sum(posts.shares) as shares, sum(posts.impressions) as views, sum(posts.engaged_users) as engaged_users, count(posts.id) as total_posts from posts inner join requests on posts.request_id=requests.id where requests.user_id=?"

MOVIE_ADDITIONS_COUNT = "select count(movie_additions.user_id) as added_movies from  movie_additions left join users on movie_additions.user_id=users.id where users.id=? AND strftime('%Y', movie_additions.date) = strftime('%Y', 'now')"
MOVIE_ADDITIONS_ALL = "select count(movie_additions.user_id) as added_movies from  movie_additions left join users on movie_additions.user_id=users.id where users.id=?"


def make(wrapped: Wrapped):
    x = 1000

    img = Image.open(TEMPLATE).convert("RGB")

    profile_picture = Image.open(wrapped.profile_picture)
    profile_picture = _center_crop(profile_picture)
    profile_picture = profile_picture.resize((250, 250))

    pp_position = (x / 2) - (profile_picture.size[0] / 2)
    pp_position = int(pp_position)

    def_separator = 67

    img.paste(profile_picture, (pp_position, def_separator + 45))
    last_x = def_separator + profile_picture.size[1] + 80

    font = ImageFont.truetype(CIRCULAR_BOLD, 60)
    draw = ImageDraw.Draw(img)

    text_width, text_height = draw.textsize(wrapped.name, font=font)
    text_position = (
        (x - text_width) // 2,
        last_x + def_separator,
    )

    draw.text(text_position, wrapped.name, font=font, fill=FONT_COLOR)

    last_x = last_x + def_separator + text_height + def_separator

    _make_header(draw, (100, last_x), title="Posts")

    last_x += 70

    _make_stat(
        draw, 100, last_x, title=_format_number(wrapped.total_posts), subtitle="Total"
    )

    _make_stat(draw, 300, last_x, title=_format_number(wrapped.views))

    _make_stat(
        draw, 550, last_x, title=_format_number(wrapped.shares), subtitle="Shares"
    )

    _make_stat(
        draw,
        750,
        last_x,
        title=_format_number(wrapped.engaged_users),
        subtitle="Engaged Users",
    )

    _make_header(draw, (100, last_x + 120), title="Contributions")

    next_x = last_x + 190

    gkeys = _format_bytes(wrapped.bytes)
    _make_stat(draw, 100, next_x, **gkeys)
    _make_stat(
        draw, 300, next_x, title=_format_number(wrapped.tickets), subtitle="Tickets"
    )
    _make_stat(
        draw,
        550,
        next_x,
        title=_format_number(wrapped.added_movies),
        subtitle="Added Movies",
    )

    _make_footer(
        draw, (100, 1050), wrapped.title or f"#{datetime.datetime.now().year}Wrapped"
    )
    _make_footer(draw, (740, 1050), "Kinobot")

    return img


def _make_footer(draw, y_x, title="#2023Wrapped"):
    number_font = ImageFont.truetype(CIRCULAR_BOLD, 40)

    draw.text(y_x, title, font=number_font, fill=FONT_COLOR)


def _make_header(draw, y_x, title="FB Posts"):
    number_font = ImageFont.truetype(CIRCULAR_BOLD, 50)

    draw.text(y_x, title, font=number_font, fill=FONT_COLOR)


def _make_stat(draw, y, x, title="10.6M", subtitle="Views"):
    number_font = ImageFont.truetype(CIRCULAR_BOLD, 60)

    text_width, text_height = draw.textsize(title, font=number_font)
    text_position = (y, x)
    draw.text(text_position, title, font=number_font, fill=FONT_COLOR)

    child_number_font = ImageFont.truetype(CIRCULAR_MEDIUM, 25)

    child_start = y
    text_position = child_start, x + text_height + 10
    draw.text(text_position, subtitle, font=child_number_font, fill=FONT_COLOR)
