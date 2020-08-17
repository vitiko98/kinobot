from facepy import GraphAPI
import json
from PIL import ImageStat


def getTokens(file):
    with open(file) as f:
        return json.load(f)


tokens = getTokens('/home/victor/.tokens')

fb = GraphAPI(tokens['facebook'])

posts = fb.get('certifiedkino/posts', limit=10)

Data = []

def get_comments(ID):
    comms = fb.get('{}/comments'.format(ID))
    if comms['data']:
        for c in comms['data']:
            Data.append({'user': c['from']['name'], 'comment': c['message']})

for i in posts['data']:
    get_comments(i['id'])


print(Data)
