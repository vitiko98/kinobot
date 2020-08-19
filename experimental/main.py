import kino_utils.comments as check_comments
import kino_utils.subs as subs
from facepy import GraphAPI

import re
import normal_kino
import argparse
import sys
import json
import datetime

tiempo = datetime.datetime.now()
tiempo_str = tiempo.strftime("Automatically executed at %H:%M:%S -4")


def args():
    parser = argparse.ArgumentParser(prog='main.py')
    parser.add_argument("--comments", metavar="json", required=True)
    parser.add_argument("--collection", metavar="path", type=str, required=True)
    parser.add_argument("--tokens", metavar="json", required=True)
    parser.add_argument("--films", metavar="json", required=True)
    return parser.parse_args()


def get_normal(collection, tokens, arbitray_movie):
    id_normal = normal_kino.main(collection, tokens)
    comment_post(tokens['facebook'], id_normal)


def get_comment_json(tokens, arguments):
    return check_comments.main(arguments.comments, tokens)


def cleansub(text):
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', text)
    return cleantext


def post_request(file, fbtoken, movie_info, request, discriminator, tiempo):
    print('Posting')
    fb = GraphAPI(fbtoken)
    disc = cleansub(discriminator)
    mes = ("{} by {}\n{}\n\nRequested by {} (!req {})\n\n"
           "{}\nThis bot is open source: https://github.com/"
           "vitiko98/Certified-Kino-Bot".format(movie_info['title'],
                                                movie_info['director(s)'],
                                                disc,
                                                request['user'],
                                                request['comment'],
                                                tiempo_str))
    id2 = fb.post(
        path = 'me/photos',
        source = open(file, 'rb'),
        published = True,
        message = mes
    )
    return id2['id']


def comment_post(fbtoken, postid):
    fb = GraphAPI(fbtoken)
    com = ('Comment your requests! Examples:\n'
    '"!req Taxi Driver 1976 [you talking to me?]"\n"!req Stalker [20:34]"'
    '\n\nhttps://kino.caretas.club')
    com_id = fb.post(
        path = postid + '/comments',
        message = com
    )
    print(com_id['id'])


def notify(fbtoken, comment_id):
    fb = GraphAPI(fbtoken)
    com_id = fb.post(
        path = comment_id + '/comments',
        message = 'Request successfully executed *beep boop*'
    )


def main():
    arguments = args()
    tokens = json.load(open(arguments.tokens))
    print('Checking comments...')
    slctd = get_comment_json(tokens, arguments)
    if slctd:
        inc = 0
        while True:
            m = slctd[inc]
            output = '/tmp/' + m['id'] + '.png'
            if not m['used']:
                m['used'] = True
                print('Request: ' + m['movie'])
                try:
                    init_sub = subs.Subs(m['movie'], m['content'], output, arguments.films)
                except:
                    pass
                if init_sub.exists:
                    print('Ok {}'.format(init_sub.movie['title']))
                    post_id = post_request(output, tokens['facebook'],
                                           init_sub.movie, m,
                                           init_sub.discriminator, tiempo)
                    comment_post(tokens['facebook'], post_id)
                    notify(tokens['facebook'], m['id'])
                    with open(arguments.comments, 'w') as c:
                        json.dump(slctd, c)
                    break
            inc += 1
            if inc == len(slctd):
                get_normal(arguments.collection, tokens, arbitray_movie=None)
                break
    else:
        get_normal(arguments.collection, tokens, arbitray_movie=None)


if __name__ == "__main__":
    sys.exit(main())
