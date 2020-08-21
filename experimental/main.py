from facepy import GraphAPI

import re
import kino_utils.comments as check_comments
import kino_utils.subs as subs
import imageio
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


def post_request(file, fbtoken, movie_info, request, discriminator, tiempo, gif=True):
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
    if not gif:
        id2 = fb.post(
            path = 'me/photos',
            source = open(file, 'rb'),
            published = True,
            message = mes
        )
    else:
        id2 = fb.post(
            path = 'me/videos',
            source = open(file, 'rb'),
            published = True,
            title = movie_info['title'],
            description = mes
        )
    return id2['id']


def comment_post(fbtoken, postid):
    fb = GraphAPI(fbtoken)
    com = ('Comment your requests! Examples:\n'
    '"!req Taxi Driver [you talking to me?]"\n"!req Stalker [20:34]"'
    '\n"!req Blade Runner [tears in rain] [gif]"'
    '\n\nhttps://kino.caretas.club')
    com_id = fb.post(
        path = postid + '/comments',
        message = com
    )
    print(com_id['id'])


def notify(fbtoken, comment_id, content):
    fb = GraphAPI(fbtoken)
    noti = ("Your request [!req {}] was successfully executed.\n\n"
            "Remember: if you've requested an unavailable film, you are "
            "ruining the fun and making the bot look ugly.".format(content))
    fb.post(path = comment_id + '/comments', message = noti)


def write_js(arguments, slctd):
    with open(arguments.comments, 'w') as c:
        json.dump(slctd, c)


def main():
    arguments = args()
    tokens = json.load(open(arguments.tokens))
    slctd = get_comment_json(tokens, arguments)
    print(slctd)
    if slctd:
        inc = 0
        while True:
            m = slctd[inc]
            if not m['used']:
                m['used'] = True
                print('Request: ' + m['movie'])
                try:
                    init_sub = subs.Subs(m['movie'], m['content'],
                                         arguments.films, is_gif=m['gif'])
                    if m['gif']:
                        print('Getting gif...')
                        output = '/tmp/' + m['id'] + '.gif'
                        imageio.mimsave(output, init_sub.pill)
                        post_id = post_request(output, tokens['facebook'],
                                               init_sub.movie, m,
                                               init_sub.discriminator, tiempo,
                                               gif=True)
                    else:
                        print('Getting png...')
                        output = '/tmp/' + m['id'] + '.png'
                        init_sub.pill.save(output)
                        post_id = post_request(output, tokens['facebook'],
                                               init_sub.movie, m,
                                               init_sub.discriminator, tiempo,
                                               gif=False)

                    write_js(arguments, slctd)
                    comment_post(tokens['facebook'], post_id)
                    notify(tokens['facebook'], m['id'], m['comment'])
                    break
                except (TypeError, AttributeError):
                    write_js(arguments, slctd)
                    pass

            inc += 1
            if inc == len(slctd):
                get_normal(arguments.collection, tokens, arbitray_movie=None)
                break
    else:
        get_normal(arguments.collection, tokens, arbitray_movie=None)


if __name__ == "__main__":
    sys.exit(main())
