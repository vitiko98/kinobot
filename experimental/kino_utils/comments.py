from facepy import GraphAPI
import random
import sys
import re
import json


def is_dupe(id_, iterable):
    for i in iterable:
        if i['id'] == id_:
            return True


def get_comments(ID, Data, fb):
    comms = fb.get('{}/comments'.format(ID))
    if comms['data']:
        for c in comms['data']:
            comentario = c['message']
            if ('!req' in comentario and c['from']['id'] != '111665010589899'
                and not is_dupe(c['id'], Data)):
                try:
                    comentario = comentario.replace('!req ', '')
                    title = comentario.split('[')[0].rstrip()
                    content = re.match(r"[^[]*\[([^]]*)\]", comentario).groups()[0]
                    Data.append({'user': c['from']['name'], 'comment': comentario,
                                'movie': title, 'content': content, 'id': c['id'],
                                'used': False})
                except AttributeError:
                    pass


def main(file, tokens):
    with open(file, 'r') as json_:
        Data = json.load(json_)
        fb = GraphAPI(tokens['facebook'])
        posts = fb.get('certifiedkino/posts', limit=2)
        for i in posts['data']:
            get_comments(i['id'], Data, fb)
    with open(file, 'w') as js:
        random.shuffle(Data)
        json.dump(Data, js)
        return Data
