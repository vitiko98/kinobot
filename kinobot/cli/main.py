import json
import logging
import os
import random
import re
import sqlite3
from datetime import datetime
from functools import reduce

import cv2
import facepy
import requests
import srt
from facepy import GraphAPI

import inspect
import sys

current_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

import utils.db_client as db_client
import utils.kino_exceptions as kino_exceptions
import utils.normal_kino as normal_kino
import utils.random_picks as random_picks
import utils.subs as subs


FACEBOOK = os.environ.get("FACEBOOK")
FILM_COLLECTION = os.environ.get("FILM_COLLECTION")
LOG = os.environ.get("KINOLOG")
COMMENTS_JSON = os.environ.get("COMMENTS_JSON")
INSTAGRAM = os.environ.get("INSTAGRAM_PASSWORD")
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


def get_normal():
    id_normal = normal_kino.main(FILM_COLLECTION, FB, TIME)
    comment_post(id_normal)


def cleansub(text):
    cleanr = re.compile("<.*?>")
    return re.sub(cleanr, "", text)


def check_directory():
    if not os.path.isdir(FILM_COLLECTION):
        sys.exit("Collection not mounted")


def update_database(movie, user):
    if not PUBLISHED:
        return
    conn = sqlite3.connect(os.environ.get("KINOBASE"))
    logging.info("Updating requests count for movie {}".format(movie["title"]))
    conn.execute(
        "UPDATE MOVIES SET requests=requests+1 WHERE title=?", (movie["title"],)
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
    conn.commit()
    conn.close()


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
    is_episode=False,
    is_multiple=True,
    normal_request=True,
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
    req_text = "!req" if normal_request else "!replace"
    mes = (
        "{}\n\nRequested by {} ({} {})\n\n"
        "{}\nThis bot is open source: https://github.com/vitiko98/Certified-Kino-Bot".format(
            title, request["user"], req_text, request["comment"], TIME
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


def comment_post(postid):
    if not PUBLISHED:
        return
    logging.info("Making collage")
    desc = random_picks.get_rec(MOVIES)
    desc.save("/tmp/tmp_collage.png")
    com = (
        "Explore the collection (+600 Movies):\nhttps://kino.caretas.club\n"
        "Are you a top user?\nhttps://kino.caretas.club/users/all\n"
        'Request examples:\n"!req Taxi Driver [you talking to me?]"\n"!req Stalker [20:34]"\n'
        '"!req A Man Escaped [21:03] [23:02]"'
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
        noti = (
            "Kinobot returned an error: {}. Please, don't forget "
            "to check the list of available films and instructions"
            " before making a request: https://kino.caretas.club".format(reason)
        )
    try:
        FB.post(path=comment_id + "/comments", message=noti)
    except facepy.exceptions.FacebookError:
        logging.info("Comment was deleted")


def read_comments_js():
    with open(COMMENTS_JSON, "r") as j:
        return json.load(j)


def write_js(slctd):
    with open(COMMENTS_JSON, "w") as c:
        json.dump(slctd, c)


def handle_requests(slctd):
    inc = 0
    while True:
        m = slctd[inc]
        if not m["used"]:
            m["used"] = True  # if m["normal_request"] else False
            # Handle old request format
            try:
                m["normal_request"] = m["normal_request"]
            except KeyError:
                m["normal_request"] = True

            logging.info(
                "Request: {} [Normal: {}]".format(
                    m["movie"].upper(), m["normal_request"]
                )
            )
            try:
                # Avoid too long requests
                if len(m["content"]) > 9:
                    logging.error("Request is too long")
                    raise TypeError
                # Check if it's a valid replace request
                if not m["normal_request"] and len(m["content"]) != 2:
                    logging.error("Invalid replace request")
                    raise TypeError
                # Avoid episodes (for now)
                if m["episode"]:
                    raise TypeError

                is_multiple = (
                    True if len(m["content"]) > 1 and m["normal_request"] else False
                )

                Frames = []
                replace_text = None if m["normal_request"] else m["content"]

                for frame in m["content"]:
                    Frames.append(
                        subs.Subs(
                            m["movie"],
                            frame,
                            MOVIES,
                            is_episode=False,
                            multiple=is_multiple,
                            replace=replace_text,
                        )
                    )
                    if not m["normal_request"]:
                        break

                if is_multiple:
                    quote_list = [word.discriminator for word in Frames]
                    if Frames[0].isminute:
                        discriminator = "Minutes: " + ", ".join(quote_list)
                    else:
                        discriminator = ", ".join(quote_list)
                else:
                    if Frames[0].isminute:
                        discriminator = "Minute: " + Frames[0].discriminator
                    else:
                        discriminator = Frames[0].discriminator
                final_image_list = [im.pill for im in Frames]
                single_image_list = reduce(lambda x, y: x + y, final_image_list)
                output_list = save_images(single_image_list)

                post_id = post_request(
                    output_list,
                    Frames[0].movie,
                    discriminator,
                    m,
                    False,
                    is_multiple,
                    m["normal_request"],
                )
                try:
                    comment_post(post_id)
                except requests.exceptions.MissingSchema:
                    logging.error("Error making the collage")
                notify(m["id"], m["comment"])
                update_database(Frames[0].movie, m["user"])
                break
            except (FileNotFoundError, OSError) as error:
                logging.error(error, exc_info=True)
                logging.info("Turning used to False")
                m["used"] = False
            except Exception as error:
                logging.error(error, exc_info=True)
                message = type(error).__name__
                notify(m["id"], m["comment"], reason=message)
            finally:
                logging.info("Updating comments json. Used: {}".format(m["used"]))
                write_js(slctd)
        inc += 1
        if inc == len(slctd):
            #            get_normal()
            break


def main():
    check_directory()
    slctd = read_comments_js()
    if slctd:
        handle_requests(slctd)
    #    else:
    #        get_normal()
    logging.info("FINISHED\n" + "#" * 70)


if __name__ == "__main__":
    sys.exit(main())
