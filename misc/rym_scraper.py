# Scrape RYM film charts to get beautiful dictionaries.

import glob
import re
import json
from bs4 import BeautifulSoup as bs4

htmls = glob.glob("htmls/*.html")


def get_genres(int, soup):
    array = int + 1
    s = 5
    Genres = []
    while True:
        var = soup.select('tr:nth-child(%s) > '
                          'td:nth-child(3) > div:nth-child(1) > '
                          'a:nth-child(%s)' % (array, s))
        if var:
            for i in var:
                Genres.append(i.text)
        else:
            break
        s += 1
    return ', '.join(Genres)


def get_dicts(file):
    soup = bs4(open(file), "html.parser")

    Films = soup.select('td:nth-child(3) > div:nth-child(1) > span:nth-child(1)')
    Years = soup.select('td:nth-child(3) > div:nth-child(1) > span:nth-child(2)')

    for m, y, n in zip(Films, Years, range(len(Films))):
        if '[' and ']' in m.text:
            title = re.sub(r'\[.+\]', '', m.text)
        else:
            title = m.text
            print(title)
            Items.append({'title': title,
                          'year': re.sub(r'[()]', '', y.text),
                          'genres': get_genres(n, soup)})


Items = []

for f in htmls:
    get_dicts(f)

with open('genres.json', 'w') as j:
    json.dump({'films': Items}, j, ensure_ascii=False)
