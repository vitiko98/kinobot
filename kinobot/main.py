import datetime
import json
import logging
import os
import random
import re
import sys
from functools import reduce

import cv2
import facepy
import requests
import srt
from facepy import GraphAPI

import kinobot_utils.comments as check_comments
import kinobot_utils.kino_exceptions as kino_exceptions
import kinobot_utils.normal_kino as normal_kino
import kinobot_utils.random_picks as random_picks
import kinobot_utils.subs as subs

FACEBOOK = os.environ.get("FACEBOOK")
FILM_COLLECTION = os.environ.get("FILM_COLLECTION")
LOG = os.environ.get("KINOLOG")
TV_COLLECTION = os.environ.get("TV_COLLECTION")
MOVIE_JSON = os.environ.get("MOVIE_JSON")
TV_JSON = os.environ.get("TV_JSON")
COMMENTS_JSON = os.environ.get("COMMENTS_JSON")
INSTAGRAM = os.environ.get("INSTAGRAM_PASSWORD")
MONKEY_PATH = os.environ.get("MONKEY_PATH")
FB = GraphAPI(FACEBOOK)

tiempo = datetime.datetime.now()
tiempo_str = tiempo.strftime("Automatically executed at %H:%M:%S GMT-4")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(module)s.%(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(LOG), logging.StreamHandler()],
)


PUBLISHED = False
if PUBLISHED:
    logging.info("STARTING: Published mode")
else:
    logging.info("STARTING: Unpublished mode")


def get_normal():
    id_normal = normal_kino.main(FILM_COLLECTION, TV_COLLECTION, FB, tiempo_str)
    comment_post(id_normal)


def cleansub(text):
    cleanr = re.compile("<.*?>")
    cleantext = re.sub(cleanr, "", text)
    return cleantext


def check_directory():
    if not os.path.isdir(FILM_COLLECTION):
        sys.exit("Collection not mounted")


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
    return final["id"]


def post_request(
    file,
    movie_info,
    discriminator,
    request,
    tiempo,
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
        "{}\n\nRequested by {} (!req {})\n\n"
        "{}\nThis bot is open source: https://github.com/vitiko98/Certified-Kino-Bot".format(
            title, request["user"], request["comment"], tiempo_str
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
        return id2["id"]


def comment_post(postid):
    desc = random_picks.get_rec(MOVIE_JSON)
    desc.save("/tmp/tmp_collage.png")
    com = (
        "Complete list (~600 Movies): https://kino.caretas.club\n"
        '\nRequest examples:\n"!req Taxi Driver [you talking to me?]"\n"!req Stalker [20:34]"\n'
        '"!req A Man Escaped [24:12] [54:10]"'
        #'"!req The Wire s01e01 [this america, man] [40:30]"'
    )
    FB.post(
        path=postid + "/comments",
        source=open("/tmp/tmp_collage.png", "rb"),
        message=com,
    )
    logging.info(postid)


def notify(comment_id, content, reason=None):
    if not reason:
        noti = (
            "202: Your request was successfully executed."
            "\n\nI haven't added over 600 movies (and increasing) in vain! If you "
            "request the SAME MOVIE too many times, your requests will be disabled."
            " Check the list of available films: https://kino.caretas.club"
        )
    else:
        noti = (
            "Kinobot returned an error: {}. Please, don't forget "
            "to check the list of available films, episodes and instructions"
            " before making a request: https://kino.caretas.club".format(reason)
        )
    if not PUBLISHED:
        return
    try:
        FB.post(path=comment_id + "/comments", message=noti)
    except facepy.exceptions.FacebookError:
        logging.info("Comment was deleted")


def write_js(slctd):
    with open(COMMENTS_JSON, "w") as c:
        json.dump(slctd, c)


def handle_requests(slctd):
    inc = 0
    while True:
        m = slctd[inc]
        if not m["used"]:
            m["used"] = True
            logging.info("Request: " + m["movie"].upper())
            try:
                # Avoid too long requests
                if len(m["content"]) > 6:
                    raise TypeError
                # Avoid episodes (for now)
                if m["episode"]:
                    raise TypeError
                is_multiple = True if len(m["content"]) > 1 else False
                Frames = []
                for frame in m["content"]:
                    Frames.append(
                        subs.Subs(
                            m["movie"],
                            frame,
                            MOVIE_JSON,
                            TV_JSON,
                            is_episode=False,
                            multiple=is_multiple,
                        )
                    )

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
                    tiempo,
                    False,
                )
                write_js(slctd)
                comment_post(post_id)
                notify(m["id"], m["comment"])
                break
            except requests.exceptions.MissingSchema:
                logging.error("Error making the collage")
                break
            except Exception as error:
                logging.error(error, exc_info=True)
                message = type(error).__name__
                write_js(slctd)
                notify(m["id"], m["comment"], reason=message)
        inc += 1
        if inc == len(slctd):
            #            get_normal()
            break


def main():
    check_directory()
    slctd = check_comments.main(COMMENTS_JSON, FB)
    if slctd:
        handle_requests(slctd)
    #    else:
    #        get_normal()
    logging.info("FINISHED\n" + "#" * 70)


if __name__ == "__main__":
    sys.exit(main())
