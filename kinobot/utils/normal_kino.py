import logging

from utils.frame import Frame
from utils.randomorg import getRandom
from utils.scan import Scan
from utils.tmdb import TMDB

logger = logging.getLogger(__name__)


def fbPost(file, FB, description):
    id2 = FB.post(
        path="me/photos", source=open(file, "rb"), published=False, message=description
    )
    return id2["id"]


def main(movie_collection, FB, tiempo_str):
    # scan for movies and get footnote
    scan = Scan(movie_collection)
    randomMovieN = getRandom(0, len(scan.movies))
    randomMovie = scan.movies[randomMovieN]

    logger.info("Processing {}".format(randomMovie))
    # save frame and get info
    frame = Frame(randomMovie)
    frame.getFrame()
    savePath = "/tmp/{}.png".format(frame.selected_frame)
    frame.image.save(savePath)

    # get info from tmdb
    info = TMDB(randomMovie)
    # get description

    def header():
        if info.is_movie:
            return (
                "{} by {} ({})\nFrame: {}\n{}\n"
                "\n{}\nThis bot is open source: https://gith"
                "ub.com/vitiko98/Certified-Kino-Bot"
            ).format(
                info.pretty_title,
                info.directors,
                info.year,
                frame.selected_frame,
                info.countries,
                tiempo_str,
            )
        else:
            return (
                "{} - {}{}\nFrame: {}\n"
                "\n{}\nThis bot is open source: https://gith"
                "ub.com/vitiko98/Certified-Kino-Bot"
            ).format(
                info.title, info.season, info.episode, frame.selected_frame, tiempo_str
            )

    description = header()
    logger.info(description)
    # post
    return fbPost(savePath, FB, description)
