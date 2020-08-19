import srt
import sys
import os
import datetime
import subprocess
import json
from fuzzywuzzy import fuzz
from fuzzywuzzy import process


def search_movie(file, search):
    with open(file, 'r') as j:
        films = json.load(j)
        print(process.extract(search, films, limit=3, scorer=fuzz.token_set_ratio))
        initial = 0
        List = []
        for f in films:
            title = fuzz.ratio(search, f['title'])
            ogtitle = fuzz.ratio(search, f['original_title'])
            if title > ogtitle:
                fuzzy = title
            else:
                fuzzy = ogtitle

            if fuzzy > initial:
                initial = fuzzy
                List.append(f)
        print(List[-1]['title'])
        return List[-1]


search_movie(sys.argv[1], sys.argv[2])

