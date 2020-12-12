# Collect requests from Facebook comments
import json
import logging
import os
import re
import sqlite3
import sys

from facepy import GraphAPI

COMMENTS_JSON = os.environ.get("COMMENTS_JSON")
REQUESTS_DB = os.environ.get("REQUESTS_DB")
FACEBOOK = os.environ.get("FACEBOOK")
KINOLOG_COMMENTS = os.environ.get("KINOLOG_COMMENTS")
REQUESTS_COMMANDS = ("!req", "!country", "!year", "!director")
FB = GraphAPI(FACEBOOK)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(module)s.%(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(KINOLOG_COMMENTS), logging.StreamHandler()],
)


def create_table():
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
                    used    BOOLEAN DEFAULT (0)
                    );"""
            )
            logging.info("Created new table")
        except sqlite3.OperationalError:
            logging.info("The table was already created")


def legacy_json_to_db():
    with open(COMMENTS_JSON, "r") as json_:
        with sqlite3.connect(REQUESTS_DB) as conn:
            Data = json.load(json_)
            for i in Data:
                try:
                    is_normal = i["normal_request"]
                except KeyError:
                    is_normal = True
                if not is_normal:
                    continue
                try:
                    conn.execute(
                        """insert into requests
                                (user, comment, type, movie, content, id,
                                used) values (?,?,?,?,?,?,?)""",
                        (
                            i["user"],
                            i["comment"],
                            "req",
                            i["movie"],
                            "|".join(i["content"]),
                            i["id"],
                            i["used"],
                        ),
                    )
                except sqlite3.IntegrityError:
                    continue
                logging.info("Added: " + i["comment"])
            conn.commit()


def get_comments(ID, fb):
    comms = fb.get(ID + "/comments")
    if not comms["data"]:
        logging.info("Nothing found")
        return
    count = 0
    with sqlite3.connect(REQUESTS_DB) as conn:
        for c in comms["data"]:
            # ignore bot comments
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
                logging.info("Ignored comment for following error: " + str(e))
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
            logging.info("New requests added with type: " + str(requests_command))
            count += 1
        conn.commit()
    logging.info("New comments found in post: " + str(count))
    return count


def main():
    posts = FB.get("certifiedkino/posts", limit=2)
    count = 0
    for i in posts["data"]:
        new_comments = get_comments(str(i["id"]), FB)
        if new_comments:
            count = new_comments + count
    logging.info("Total new comments added: " + str(count))


if __name__ == "__main__":
    sys.exit(main())
