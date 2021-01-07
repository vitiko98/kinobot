#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import logging
import re
import sqlite3

import click
from facepy import GraphAPI

from kinobot import FACEBOOK, KINOLOG_COMMENTS, REQUESTS_DB
from kinobot.db import create_request_db
from kinobot.utils import kino_log

COMMANDS = ("!req", "!country", "!year", "!director")
REQUEST_RE = re.compile(r"[^[]*\[([^]]*)\]")
FB = GraphAPI(FACEBOOK)


def dissect_comment(comment):
    split_command = comment.split(" ")
    requests_command = split_command[0]
    if not any(commands in requests_command.lower() for commands in COMMANDS):
        return

    split_command.pop(0)
    final_comment = " ".join(split_command)

    try:
        title = final_comment.split("[")[0].rstrip()
    except IndexError:
        return

    content = REQUEST_RE.findall(final_comment)
    if content:
        return {
            "command": requests_command,
            "title": title,
            "comment": final_comment,
            "content": content,
        }


def add_comments(post_id):
    """
    :param post_id: Facebook post ID
    """
    comms = FB.get(post_id + "/comments")

    if not comms["data"]:
        logging.info("Nothing found")
        return

    count = 0
    with sqlite3.connect(REQUESTS_DB) as conn:
        for c in comms["data"]:
            # Ignore bot comments
            if c["from"]["id"] == "111665010589899":
                continue
            comment = c["message"]
            comment_dict = dissect_comment(comment)
            if not comment_dict:
                continue
            try:
                conn.execute(
                    """insert into requests
                            (user, comment, type, movie, content, id)
                            values (?,?,?,?,?,?)""",
                    (
                        c["from"]["name"],
                        comment_dict.get("comment"),
                        comment_dict.get("command"),
                        comment_dict.get("title"),
                        "|".join(comment_dict.get("content")),
                        c["id"],
                    ),
                )
            except sqlite3.IntegrityError:
                continue

            logging.info(f"New requests added with type: {comment_dict.get('command')}")
            count += 1

        conn.commit()

    logging.info(f"New comments found in post: {count}")
    return count


@click.command()
@click.option("--count", "-c", default=25, help="number of posts to scan")
def collect(count):
    """
    Collect 'requests' from Kinobot's last <n> posts.
    """
    kino_log(KINOLOG_COMMENTS)

    create_request_db()

    logging.info(f"About to scan {count} posts")
    posts = FB.get("certifiedkino/posts", limit=count)

    count_ = 0
    for i in posts["data"]:
        new_comments = add_comments(str(i["id"]))
        if new_comments:
            count_ = new_comments + count_

    logging.info(f"Total new comments added: {count_}")
