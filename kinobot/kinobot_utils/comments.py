import json
import logging
import random
import re

logger = logging.getLogger(__name__)


def is_dupe(id_, iterable):
    for i in iterable:
        if i["id"] == id_:
            return True


# ignoring gifs for now
def get_comments(ID, Data, fb):
    comms = fb.get("{}/comments".format(ID))
    if comms["data"]:
        for c in comms["data"]:
            comentario = c["message"]
            if (
                "!req" in comentario
                and c["from"]["id"] != "111665010589899"
                and not is_dupe(c["id"], Data)
            ):
                try:
                    comentario = comentario.replace("!req ", "")
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
                            "used": False,
                        }
                    )
                    logger.info("New comment added")
                except AttributeError:
                    pass


def main(file, FB):
    with open(file, "r") as json_:
        Data = json.load(json_)
        posts = FB.get("certifiedkino/posts", limit=20)
        for i in posts["data"]:
            get_comments(i["id"], Data, FB)
    with open(file, "w") as js:
        random.shuffle(Data)
        json.dump(Data, js)
        return Data
