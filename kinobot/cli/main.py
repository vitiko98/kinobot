import inspect
import json
import logging
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime
from functools import reduce

import cv2
import facepy
import requests
import srt
from facepy import GraphAPI

current_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

import utils.db_client as db_client
import utils.discover as discover
import utils.kino_exceptions as kino_exceptions
import utils.normal_kino as normal_kino
import utils.random_picks as random_picks
import utils.subs as subs

FACEBOOK = os.environ.get("FACEBOOK")
FILM_COLLECTION = os.environ.get("FILM_COLLECTION")
LOG = os.environ.get("KINOLOG")
REQUESTS_DB = os.environ.get("REQUESTS_DB")
COMMANDS = ("!req", "!country", "!year", "!director")
FB = GraphAPI(FACEBOOK)
MOVIES = db_client.get_complete_list()
TIME = datetime.now().strftime("Automatically executed at %H:%M GMT-4")
PUBLISHED = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(module)s.%(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(LOG), logging.StreamHandler()],
)


if PUBLISHED:
    logging.info("STARTING: Published mode")
else:
    logging.info("STARTING: Unpublished mode")


def check_directory():
    if not os.path.isdir(FILM_COLLECTION):
        sys.exit("Collection not mounted")


def get_requests():
    with sqlite3.connect(REQUESTS_DB) as conn:
        result = conn.execute("select * from requests where used=0").fetchall()
        return [
            {
                "user": i[0],
                "comment": i[1],
                "type": i[2],
                "movie": i[3],
                "content": i[4].split("|"),
                "id": i[5],
            }
            for i in result
        ]


def block_user(user, check=False):
    if not PUBLISHED:
        return
    with sqlite3.connect(os.environ.get("KINOBASE")) as conn:
        try:
            logging.info("Adding user: {}".format(user))
            conn.execute("INSERT INTO USERS (name) VALUES (?)", (user,))
        except sqlite3.IntegrityError:
            logging.info("Already added")
        if check:
            if conn.execute(
                "select blocked from users where name=?", (user,)
            ).fetchone()[0]:
                raise kino_exceptions.BlockedUser
            return
        logging.info("Blocking user: {}".format(user))
        conn.execute("UPDATE USERS SET blocked=1 WHERE name=?", (user,))
        conn.commit()


def update_database(movie, user):
    if not PUBLISHED:
        return
    with sqlite3.connect(os.environ.get("KINOBASE")) as conn:
        logging.info("Updating requests count for movie {}".format(movie["title"]))
        conn.execute(
            "UPDATE MOVIES SET requests=requests+1 WHERE title=?", (movie["title"],)
        )
        logging.info(
            "Updating last_request timestamp for movie {}".format(movie["title"])
        )
        timestamp = int(time.time())
        conn.execute(
            "UPDATE MOVIES SET last_request=? WHERE title=?",
            (
                timestamp,
                movie["title"],
            ),
        )
        try:
            logging.info("Adding user: {}".format(user))
            conn.execute("INSERT INTO USERS (name) VALUES (?)", (user,))
        except sqlite3.IntegrityError:
            logging.info("Already added")
        logging.info("Updating requests count")
        conn.execute("UPDATE USERS SET requests=requests+1 WHERE name=?", (user,))
        if movie["popularity"] <= 9:
            logging.info("Updating digs count ({})".format(movie["popularity"]))
            conn.execute("UPDATE USERS SET digs=digs+1 WHERE name=?", (user,))
        if movie["budget"] <= 750000:
            logging.info("Updating indie count ({})".format(movie["budget"]))
            conn.execute("UPDATE USERS SET indie=indie+1 WHERE name=?", (user,))
        if movie["year"] < 1940:
            logging.info("Updating historician count ({})".format(movie["budget"]))
            conn.execute(
                "UPDATE USERS SET historician=historician+1 WHERE name=?", (user,)
            )
        conn.commit()


def save_images(pil_list):
    nums = random.sample(range(10000), len(pil_list))
    names = ["/tmp/{}.png".format(i) for i in nums]
    for im, nam in zip(pil_list, names):
        im.save(nam)
    return names


def post_multiple(images, message):
    IDs = []
    for image in images:
        IDs.append(
            {
                "media_fbid": FB.post(
                    path="me/photos", source=open(image, "rb"), published=False
                )["id"]
            }
        )
    final = FB.post(
        path="me/feed",
        attached_media=json.dumps(IDs),
        message=message,
        published=PUBLISHED,
    )
    logging.info(
        "Posted: https://www.facebook.com/certifiedkino/posts/{}".format(
            final["id"].split("_")[-1]
        )
    )
    return final["id"]


def post_request(
    file,
    movie_info,
    discriminator,
    request,
    request_command="!req",
    is_episode=False,
    is_multiple=True,
):
    if is_episode:
        title = "{} - {}{}".format(
            movie_info["title"], movie_info["season"], movie_info["episode"]
        )
    else:
        if (
            movie_info["title"].lower() != movie_info["original_title"].lower()
            and len(movie_info["original_title"]) < 45
        ):
            pretty_title = "{} [{}]".format(
                movie_info["original_title"], movie_info["title"]
            )
        else:
            pretty_title = movie_info["title"]
        title = "{} ({})\nDirector: {}\nCategory: {}".format(
            pretty_title,
            movie_info["year"],
            movie_info["director"],
            movie_info["category"],
        )

    logging.info("Posting")
    mes = (
        "{}\n\nRequested by {} ({} {})\n\n"
        "{}\nThis bot is open source: https://github.com/vitiko98/kinobot".format(
            title, request["user"], request_command, request["comment"], TIME
        )
    )
    if len(file) > 1:
        return post_multiple(file, mes)
    else:
        id2 = FB.post(
            path="me/photos",
            source=open(file[0], "rb"),
            published=PUBLISHED,
            message=mes,
        )
        logging.info(
            "Posted: https://www.facebook.com/certifiedkino/photos/{}".format(id2["id"])
        )
        return id2["id"]


def comment_post(postid, movie_length=600):
    if not PUBLISHED:
        return
    logging.info("Making collage")
    desc = random_picks.get_rec(MOVIES)
    desc.save("/tmp/tmp_collage.png")
    com = (
        "Explore the collection ({} Movies):\nhttps://kino.caretas.club\n"
        "Are you a top user?\nhttps://kino.caretas.club/users/all\n"
        'Request examples:\n"!req Taxi Driver [you talking to me?]"\n"!req Stalker [20:34]"\n'
        '"!req A Man Escaped [21:03] [23:02]"'.format(movie_length)
    )
    FB.post(
        path=postid + "/comments",
        source=open("/tmp/tmp_collage.png", "rb"),
        message=com,
    )
    logging.info("Commented")


def notify(comment_id, content, reason=None):
    if not PUBLISHED:
        return
    if not reason:
        noti = (
            "202: Your request was successfully executed.\n"
            "Are you in the list of top users? https://kino.caretas.club/users/all\n"
            "Check the complete list of movies: https://kino.caretas.club"
        )
    else:
        if "offen" in reason.lower():
            noti = (
                "An offensive word has been detected when processing your request. "
                "You are blocked.\n\nSend a PM if you believe this was accidental."
            )
        else:
            noti = (
                "Kinobot returned an error: {}. Please, don't forget "
                "to check the list of available films and instructions"
                " before making a request: https://kino.caretas.club".format(reason)
            )
    try:
        FB.post(path=comment_id + "/comments", message=noti)
    except facepy.exceptions.FacebookError:
        logging.info("Comment was deleted")


def update_request_to_used(request_id):
    with sqlite3.connect(REQUESTS_DB) as conn:
        logging.info("Updating request as used...")
        conn.execute(
            "update requests set used=1 where id=?",
            (request_id,),
        )
        conn.commit()


class Images:
    def __init__(self, m: dict, is_multiple: bool):
        self.m = m
        self.is_multiple = is_multiple
        self.discriminator = None
        self.Frames = []

    def get_images(self):
        for frame in self.m["content"]:
            self.Frames.append(
                subs.Subs(
                    self.m["movie"],
                    frame,
                    MOVIES,
                    is_episode=False,
                    multiple=self.is_multiple,
                    replace=None,
                )
            )

        if self.is_multiple:
            quote_list = [word.discriminator for word in self.Frames]
            if self.Frames[0].isminute:
                self.discriminator = "Minutes: " + ", ".join(quote_list)
            else:
                self.discriminator = ", ".join(quote_list)
        else:
            if self.Frames[0].isminute:
                self.discriminator = "Minute: " + self.Frames[0].discriminator
            else:
                self.discriminator = self.Frames[0].discriminator
        final_image_list = [im.pill for im in self.Frames]
        single_image_list = reduce(lambda x, y: x + y, final_image_list)
        if len(single_image_list) < 4:
            single_image_list = [random_picks.get_collage(single_image_list, False)]
        self.final_images = save_images(single_image_list)


def handle_requests():
    requests_ = get_requests()
    random.shuffle(requests_)
    for m in requests_:
        try:
            block_user(m["user"], check=True)
            request_command = m["type"]

            if len(m["content"]) > 20 or len(m["content"][0]) > 130:
                raise kino_exceptions.TooLongRequest

            logging.info("Request command: {} {}".format(request_command, m["comment"]))

            if "req" not in request_command:
                if len(m["content"]) != 1:
                    raise kino_exceptions.BadKeywords

                req_dict = discover.discover_movie(
                    m["movie"], request_command.replace("!", ""), m["content"][0]
                )
                m["movie"] = req_dict["title"] + " " + str(req_dict["year"])
                m["content"] = [req_dict["quote"]]

            is_multiple = True if len(m["content"]) > 1 else False
            images = Images(m, is_multiple)
            images.get_images()
            post_id = post_request(
                images.final_images,
                images.Frames[0].movie,
                images.discriminator,
                m,
                request_command,
                False,
                is_multiple,
            )
            try:
                comment_post(post_id, movie_length=len(MOVIES))
            except requests.exceptions.MissingSchema:
                logging.error("Error making the collage")
            notify(m["id"], m["comment"])
            update_database(images.Frames[0].movie, m["user"])
            update_request_to_used(m["id"])
            logging.info("Request finished successfully")
            break
        except kino_exceptions.RestingMovie:
            # ignore recently requested movies
            continue
        except (FileNotFoundError, OSError) as error:
            # to check missing or corrupted files
            logging.error(error, exc_info=True)
            continue
        except kino_exceptions.BlockedUser:
            update_request_to_used(m["id"])
        except Exception as error:
            logging.error(error, exc_info=True)
            update_request_to_used(m["id"])
            message = type(error).__name__
            if "offens" in message.lower():
                block_user(m["user"])
            notify(m["id"], m["comment"], reason=message)


def main():
    check_directory()
    handle_requests()
    logging.info("FINISHED\n" + "#" * 70)


if __name__ == "__main__":
    sys.exit(main())
