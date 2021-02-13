#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import logging
import re
import sqlite3


from random import randint

import click
from facepy import GraphAPI

from kinobot import FACEBOOK, FACEBOOK_TV, KINOLOG_COMMENTS, REQUESTS_DB, KINOBOT_ID
from kinobot.db import (
    create_request_db,
    get_list_of_episode_dicts,
    get_list_of_movie_dicts,
)
from kinobot.exceptions import (
    MovieNotFound,
    EpisodeNotFound,
    InvalidRequest,
    OffensiveWord,
)
from kinobot.request import search_episode, search_movie
from kinobot.utils import kino_log, is_episode, is_parallel, check_offensive_content


COMMANDS = ("!req", "!parallel", "!palette", "!gif")
REQUEST_RE = re.compile(r"[^[]*\[([^]]*)\]")

MOVIE_LIST = get_list_of_movie_dicts()
EPISODE_LIST = get_list_of_episode_dicts()


logger = logging.getLogger(__name__)


def dissect_comment(comment, music=False):
    """
    :param comment: comment string
    :param music: ignore MovieNotFound and EpisodeNotFound exceptions
    :raises exceptions.MovieNotFound
    :raises exceptions.EpisodeNotFound
    :raises exceptions.OffensiveWord
    :raises exceptions.InvalidRequest
    """
    split_command = comment.split(" ")
    requests_command = split_command[0]

    if requests_command.lower() not in COMMANDS:
        return

    split_command.pop(0)
    final_comment = " ".join(split_command)

    if requests_command == "!parallel":
        parallels = is_parallel(final_comment)

        try:
            contents = [REQUEST_RE.findall(parallel) for parallel in parallels]
            if any(len(content) > 1 for content in contents) or len(parallels) > 4:
                raise InvalidRequest(
                    "Invalid parallel request: expected one field per "
                    "separator or less than 5 separators."
                )
        except TypeError:
            return

        title, content = "Parallel", ["Parallel"]
    else:
        try:
            title = final_comment.split("[")[0].rstrip()
            if not music:
                if is_episode(title):
                    search_episode(EPISODE_LIST, title, raise_resting=False)
                else:
                    search_movie(MOVIE_LIST, title, raise_resting=False)
        except IndexError:
            return
        content = REQUEST_RE.findall(final_comment)

    if music:
        title = "MUSIC" + title

    if content:
        [check_offensive_content(text) for text in content]
        return {
            "command": requests_command,
            "title": title,
            "comment": final_comment,
            "content": content,
        }


def direct_request(comment_str, **kwargs):
    """
    :param comment_str: comment/request string to be converted
    :param comment_dict: comment_dict
    """
    comment_dict = dissect_comment(comment_str, kwargs.get("music", False))
    if not comment_dict:
        raise InvalidRequest(f"Invalid request string: {comment_str}.")

    return {
        "user": kwargs.get("user", "Unknown"),
        "comment": comment_dict.get("comment"),
        "type": comment_dict.get("command"),
        "movie": comment_dict.get("title"),
        "content": comment_dict.get("content"),
        "id": randint(10000, 20000),
        "on_demand": True,
        "verified": kwargs.get("verified", 1),
        "priority": kwargs.get("priority", 1),
    }


def get_comment_tuple(comment_dict):
    """
    :param comment_dict: comment dictionary from Facebook post
    """
    if comment_dict.get("from", {}).get("id") == KINOBOT_ID:
        return

    username = comment_dict["from"]["name"]

    try:
        final_comment_dict = dissect_comment(comment_dict["message"])
        if not final_comment_dict:
            return
    except (MovieNotFound, EpisodeNotFound, OffensiveWord, InvalidRequest) as error:
        logger.info(f"Exception raised: {type(error).__name__}")
        return

    return (
        username,
        final_comment_dict.get("comment"),
        final_comment_dict.get("command"),
        final_comment_dict.get("title"),
        "|".join(final_comment_dict.get("content")),
        comment_dict["id"],
    )


def add_comments(graph_obj, post_id):
    """
    :param graph_obj: facepy.GraphAPI object
    :param post_id: Facebook post ID
    """
    comments = graph_obj.get(post_id + "/comments")

    if not comments["data"]:
        logger.info("Nothing found")
        return

    count = 0
    with sqlite3.connect(REQUESTS_DB) as conn:
        for comment in comments["data"]:
            comment_tuple = get_comment_tuple(comment)
            if not comment_tuple:
                continue

            try:
                conn.execute(
                    """insert into requests
                            (user, comment, type, movie, content, id)
                            values (?,?,?,?,?,?)""",
                    comment_tuple,
                )
                logger.info(f"New request added: {comment_tuple[2]}")
                count += 1
            except sqlite3.IntegrityError:
                continue

        conn.commit()

    logger.info(f"New comments found in post: {count}")
    return count


@click.command()
@click.option("--count", "-c", default=25, help="number of posts to scan")
def collect(count):
    """
    Collect 'requests' from Kinobot's last <n> posts.
    """
    kino_log(KINOLOG_COMMENTS)
    kinobot = GraphAPI(FACEBOOK)
    kinobot_tv = GraphAPI(FACEBOOK_TV)

    create_request_db()

    logger.info(f"About to scan {count} posts")

    count_ = 0
    for type_ in (kinobot, kinobot_tv):
        for post in type_.get("me/posts", limit=count)["data"]:
            new_comments = add_comments(type_, str(post["id"]))
            if new_comments:
                count_ = new_comments + count_

    logger.info(f"Total new comments added: {count_}")
