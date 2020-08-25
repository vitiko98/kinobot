from facepy import GraphAPI

from kinobot.frame import Frame
from kinobot.scan import Scan
from kinobot.randomorg import getRandom
from kinobot.tmdb import TMDB


def fbPost(file, description, token):
    fb = GraphAPI(token)
    id2 = fb.post(
        path = 'me/photos',
        source = open(file, 'rb'),
        published = True,
        message = description
    )
    return id2['id']


def main(collection, tokens, arbitrary=None):
    # scan for movies and get footnote
    scan = Scan(collection)
    if not arbitrary:
        # get random movie
        randomMovieN = getRandom(0, len(scan.Collection))
        randomMovie = scan.Collection[randomMovieN]
    else:
        randomMovie = arbitrary
    print('Processing {}'.format(randomMovie))
    # save frame and get info
    frame = Frame(randomMovie)
    frame.getFrame()
    savePath = '/tmp/{}.png'.format(frame.selected_frame)
    frame.image.save(savePath)

    # get info from tmdb
    info = TMDB(randomMovie, tokens['tmdb'])
    # get description

    def header():
        footnote = scan.getFootnote()
        return ('{} by {} ({})\nFrame: {}\n{}\n'
        '\n{}').format(info.title,
                       ', '.join(info.directors),
                       info.year,
                       frame.selected_frame,
                       info.countries,
                       footnote)

    description = header()
    print(description)
    # post
    return fbPost(savePath, description, tokens['facebook'])
