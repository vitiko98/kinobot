import json
import sys
import logging
import random
import re
import os
from facepy import GraphAPI

COMMENTS_JSON = os.environ.get("COMMENTS_JSON")
FACEBOOK = os.environ.get("FACEBOOK")
KINOLOG_COMMENTS = os.environ.get("KINOLOG_COMMENTS")
FB = GraphAPI(FACEBOOK)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(module)s.%(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(KINOLOG_COMMENTS), logging.StreamHandler()],
)


def is_dupe(id_, iterable):
    for i in iterable:
        if i["id"] == id_:
            return True


# ignoring gifs for now
def get_comments(ID, Data, fb):
    comms = fb.get("{}/comments".format(ID))
    if comms["data"]:
        count = 0
        for c in comms["data"]:
            comentario = c["message"]
            used = False
            if (
                ("!replace" in comentario or "!req" in comentario)
                and c["from"]["id"] != "111665010589899"
                and not is_dupe(c["id"], Data)
            ):
                try:
                    normal_request = True if "!req" in comentario else False
                    logging.info(
                        "New comment detected. Normal request: {}".format(
                            normal_request
                        )
                    )
                    if not normal_request:
                        reacts = fb.get("{}/reactions".format(c["id"]))["data"]
                        if len(reacts) < 5:
                            logging.info(
                                "Not enough reacts. Adding requests as used: {}".format(
                                    comentario
                                )
                            )
                            used = True
                    comentario = comentario.replace("!req ", "").replace(
                        "!replace ", ""
                    )
                    title = comentario.split("[")[0].rstrip()
                    pattern = re.compile(r"[^[]*\[([^]]*)\]")
                    content = pattern.findall(comentario)
                    if re.search(r"s[0-9]+e[0-9]+", comentario, flags=re.IGNORECASE):
                        is_episode = True
                    else:
                        is_episode = False
                    Data.append(
                        {
                            "user": c["from"]["name"],
                            "comment": comentario,
                            "movie": title,
                            "content": content,
                            "id": c["id"],
                            "episode": is_episode,
                            "normal_request": normal_request,
                            "used": used,
                        }
                    )
                    count += 1
                except Exception as e:
                    logging.error(e, exc_info=True)
                    pass
        logging.info("New comments found in post: {}".format(count))
        return count


def main():
    with open(COMMENTS_JSON, "r") as json_:
        Data = json.load(json_)
        posts = FB.get("certifiedkino/posts", limit=17)
        count = 0
        for i in posts["data"]:
            new_comments = get_comments(i["id"], Data, FB)
            if new_comments:
                count = new_comments + count
        logging.info("Total new comments added: {}".format(count))
    with open(COMMENTS_JSON, "w") as js:
        random.shuffle(Data)
        logging.info("Writing json")
        json.dump(Data, js)


if __name__ == "__main__":
    sys.exit(main())
