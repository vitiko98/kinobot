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

REQUESTS_COMMANDS = ("!req", "!country", "!year", "!director")
FB = GraphAPI(FACEBOOK)


def create_requests_table():
    with sqlite3.connect(REQUESTS_DB) as conn:
        try:
            conn.execute(
                """CREATE TABLE requests (
                    user    TEXT    NOT NULL,
                    comment TEXT    NOT NULL
                                    UNIQUE,
                    type    TEXT    NOT NULL,
                    movie   TEXT    NOT NULL,
                    content TEXT    NOT NULL,
                    id      TEXT    NOT NULL,
                    used    BOOLEAN DEFAULT (0),
                    verified BOOLEAN DEFAULT (0)
                    );"""
            )
            logging.info("Created new table: requests")
        except sqlite3.OperationalError:
            pass


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
            comentario = c["message"]
            try:
                split_command = comentario.split(" ")
                requests_command = split_command[0]
                if not any(
                    commands in requests_command.lower()
                    for commands in REQUESTS_COMMANDS
                ):
                    continue
                split_command.pop(0)
                comentario = " ".join(split_command)
                title = comentario.split("[")[0].rstrip()
                pattern = re.compile(r"[^[]*\[([^]]*)\]")
                content = pattern.findall(comentario)
            except Exception as e:
                logging.info(f"Ignored comment for following error: {e}")
                continue
            try:
                conn.execute(
                    """insert into requests
                            (user, comment, type, movie, content, id)
                            values (?,?,?,?,?,?)""",
                    (
                        c["from"]["name"],
                        comentario,
                        requests_command,
                        title,
                        "|".join(content),
                        c["id"],
                    ),
                )
            except sqlite3.IntegrityError:
                continue
            logging.info(f"New requests added with type: {requests_command}")
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(module)s.%(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(KINOLOG_COMMENTS), logging.StreamHandler()],
    )
    logging.info(f"About to scan {count} posts")
    create_requests_table()
    posts = FB.get("certifiedkino/posts", limit=count)
    count_ = 0
    for i in posts["data"]:
        new_comments = add_comments(str(i["id"]))
        if new_comments:
            count_ = new_comments + count_
    logging.info(f"Total new comments added: {count_}")
