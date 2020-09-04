from facepy import GraphAPI

import cv2
import random
import os
import re
import kinobot_utils.comments as check_comments
import kinobot_utils.subs as subs
import kinobot_utils.random_picks as random_picks
import normal_kino
import sys
import json
import datetime


FACEBOOK = os.environ.get('FACEBOOK')
FILM_COLLECTION = os.environ.get('FILM_COLLECTION')
TV_COLLECTION = os.environ.get('TV_COLLECTION')
MOVIE_JSON = os.environ.get('MOVIE_JSON')
TV_JSON = os.environ.get('TV_JSON')
COMMENTS_JSON = os.environ.get('COMMENTS_JSON')
MONKEY_PATH = os.environ.get('MONKEY_PATH')
FB = GraphAPI(FACEBOOK)

tiempo = datetime.datetime.now()
tiempo_str = tiempo.strftime("Automatically executed at %H:%M:%S GMT-4")


def get_monkey():
    monkey = random.choice(os.listdir(MONKEY_PATH))
    return MONKEY_PATH + monkey


def get_normal():
    id_normal = normal_kino.main(FILM_COLLECTION, TV_COLLECTION, FB, tiempo_str)
    comment_post(id_normal)


def cleansub(text):
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', text)
    return cleantext


def post_request(file, movie_info, discriminator, request, tiempo, is_episode):
    if is_episode:
        title = '{} - {}{}'.format(movie_info['title'], movie_info['season'], movie_info['episode'])
    else:
        title = '{} by {}'.format(movie_info['title'], movie_info['director(s)'])

    print('Posting')
    disc = cleansub(discriminator)
    mes = ("{}\n{}\n\nRequested by {} (!req {})\n\n"
           "{}\nThis bot is open source: https://github.com/"
           "vitiko98/Certified-Kino-Bot".format(title,
                                                disc,
                                                request['user'],
                                                request['comment'],
                                                tiempo_str))
    id2 = FB.post(
        path = 'me/photos',
        source = open(file, 'rb'),
        published = False,
        message = mes
    )
    return id2['id']


def comment_post(postid):
    desc = random_picks.get_rec(MOVIE_JSON)
    desc.save('/tmp/tmp_collage.png')
    com = ('Request examples:\n\n'
    '"!req Taxi Driver [you talking to me?]"\n"!req Stalker [20:34]"\n'
    '"!req The Wire s01e01 [this america, man]"\n"!req The Sopranos s02e03 [30:23]"'
    '\n\nhttps://kino.caretas.club')
    FB.post(
        path = postid + '/comments',
        source = open('/tmp/tmp_collage.png', 'rb'),
        message = com
    )
    print(postid)



def notify(comment_id, content, fail=False):
    monkey = get_monkey()
    if not fail:
        noti = ("Your request [!req {}] was successfully executed.\n\n"
                "Please, don't forget to check the list of available films"
                ", episodes and instructions before embarrassing the bot:"
                " https://kino.caretas.club".format(content))
    else:
        noti = ("Something went wrong with your request. Please, don't forget "
                "to check the list of available films, episodes and instructions befo"
                "re embarrassing the bot: https://kino.caretas.club")
    FB.post(path = comment_id + '/comments',
            source = open(monkey, 'rb'), message = noti)


def write_js(slctd):
    with open(COMMENTS_JSON, 'w') as c:
        json.dump(slctd, c)


def main():
    slctd = check_comments.main(COMMENTS_JSON, FB)
    print(slctd)
    if slctd:
        inc = 0
        while True:
            m = slctd[inc]
            if not m['used']:
                m['used'] = True
                print('Request: ' + m['movie'])
                try:
                    if m['episode']:
                        is_episode = True
                    else:
                        is_episode = False

                    init_sub = subs.Subs(m['movie'], m['content'],
                                         MOVIE_JSON, TV_JSON, is_episode=is_episode)

                    print('Getting png...')
                    output = '/tmp/' + m['id'] + '.png'
                    init_sub.pill.save(output)
                    post_id = post_request(output,
                                           init_sub.movie,
                                           init_sub.discriminator, m,
                                           tiempo, is_episode)

                    write_js(slctd)
                    comment_post(post_id)
        #            notify(m['id'], m['comment'])
                    break
                except (TypeError, NameError, cv2.error, AttributeError):
         #           notify(m['id'], m['comment'], fail=True)
                    write_js(slctd)
                    pass

            inc += 1
            if inc == len(slctd):
                get_normal()
                break
    else:
        get_normal()


if __name__ == "__main__":
    sys.exit(main())
