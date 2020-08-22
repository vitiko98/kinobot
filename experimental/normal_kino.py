from facepy import GraphAPI
from PIL import ImageStat

from kinobot.frame import Frame
from kinobot.palette import getPalette
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


# check if a palette is needed
def isBW(imagen):
    imagen = imagen.convert('HSV')
    hsv = ImageStat.Stat(imagen)
    if hsv.mean[1] > 25.0:
        return False
    else:
        return True


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
    saveFrame = frame.getFrame()
    savePath = '/tmp/{}.png'.format(frame.selectedFrame)
    saveFrame.save(savePath)

    # get palette if needed
    if not isBW(saveFrame):
        paleta = getPalette(saveFrame, frame.width, frame.height)
        paleta.save(savePath)

    # get info from tmdb
    info = TMDB(randomMovie, tokens['tmdb'])
    # get description

    def header():
        prob = '%3f' % (((1/len(scan.Collection)) * (1/frame.maxFrame)) * 100)
        footnote = scan.getFootnote(prob)
        return ('{} by {} ({})\nFrame: {}\n{}\n'
        '\n{}').format(info.title,
                       ', '.join(info.directors),
                       info.year,
                       frame.selectedFrame,
                       info.countries,
                       footnote)

    description = header()
    print(description)
    # post
    return fbPost(savePath, description, tokens['facebook'])
