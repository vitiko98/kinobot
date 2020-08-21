import srt
import os
import subprocess
import json
from fuzzywuzzy import fuzz


def search_movie(file, search):
    with open(file, 'r') as j:
        films = json.load(j)
        initial = 0
        List = []
        for f in films:
            title = fuzz.ratio(search, f['title'] + ' ' + str(f['year']))
            ogtitle = fuzz.ratio(search, f['original_title'] + ' ' + str(f['year']))
            if title > ogtitle:
                fuzzy = title
            else:
                fuzzy = ogtitle

            if fuzzy > initial:
                initial = fuzzy
                List.append(f)
        return List[-1]


def get_subtitle(item):
    try:
        with open(item['subtitle'], 'r') as it:
            subtitle_generator = srt.parse(it)
            return list(subtitle_generator)
    except FileNotFoundError:
        return


def find_quote(subtitle_list, words):
    initial = 0
    Words = []
    for sub in subtitle_list:
        fuzzy = fuzz.ratio(words, sub.content)
        if fuzzy > initial:
            initial = fuzzy
            Words.append({'message': sub.content,
                          'second': sub.start.seconds + 1, 'score': fuzzy})
    return Words[-1]


def get_frame(second, file, output, subtitle=None):
    if subtitle:
        subprocess.call(
            'ffmpeg -loglevel warning -ss {} -copyts -i "{}" -vf '
            'scale=iw*sar:ih,subtitles="{}" -vframes 1 {}'.format(second,
                                                                  file,
                                                                  subtitle,
                                                                  output),
            shell=True)
    else:
        subprocess.call(
            'ffmpeg -loglevel warning -ss {} -copyts -i "{}" -vf '
            'scale=iw*sar:ih -vframes 1 {}'.format(second,
                                                   file,
                                                   output),
            shell=True)


def exists(file):
    if os.path.isfile(file):
        return True
    else:
        return False


class Subs:
    def __init__(self, busqueda, words, output, json_file):
        """ search the movie """
        self.movie = search_movie(json_file, busqueda)
        """ check if second or quote """
        try:
            t = words
            m, s = t.split(':')
            sec = int(m) * 60 + int(s)
            get_frame(sec, self.movie['path'], output)
            self.discriminator = 'Minute: {}'.format(words)
            self.exists = exists(output)

        except ValueError:
            subtitles = get_subtitle(self.movie)
            if subtitles:
                quote = find_quote(subtitles, words)
                get_frame(quote['second'], self.movie['path'],
                          output, subtitle=self.movie['subtitle'])
                self.discriminator = '"{}"'.format(quote['message'])
                self.exists = exists(output)
            else:
                print('No subtitles found')
                self.exists = False
