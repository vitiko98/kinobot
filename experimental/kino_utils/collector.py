# warning: messy state

import sys
import os
import json
import scan
import tmdbsimple as tmdb

from operator import itemgetter
from guessit import guessit
from pathlib import Path


# guess from filename
def guessfile(movie):
    guess = guessit(movie, '-s')

    title = guess['title']
    try:
        year = guess['year']
        return title, year
    except KeyError:
        return False


# get info from tmdb api
class TMDB:
    def __init__(self, movie, token):
        tmdb.API_KEY = token
        try:
            self.title, self.year = guessfile(movie)

            countries = []
            directors = []

            search = tmdb.Search()
            search.movie(query=self.title, year=self.year)
            movieID = search.results[0]['id']
            self.title = search.results[0]['title']
            self.ogtitle = search.results[0]['original_title']

            movie = tmdb.Movies(movieID)

            movie.info()
            for m in movie.production_countries:
                countries.append(m['name'])

            self.countries = ', '.join(countries)
            self.popularity = movie.popularity

            movie.credits()
            for m in movie.crew:
                if 'Director' == m['job']:
                    directors.append(m['name'])
            self.directors = ', '.join(directors)

        except (IndexError, TypeError):
            print('Error with {}'.format(movie))


scanner = Scan(sys.argv[1])

with open("film_list.json", "r") as r:
    json_movies = json.load(r)

    def dupe(json_movies, movie_file):
        for i in json_movies:
            if i['path'] == movie_file:
                print('Skipping: {}'.format(movie_file))
                return True

    for i in range(len(scanner.Collection)):
        movie_file = scanner.Collection[i]
        if dupe(json_movies, movie_file):
            pass
        else:
            print('Adding {}'.format(movie_file))
            name = os.path.basename(movie_file)
            to_srt = Path(name).with_suffix('')
            srt_file = '/home/victor/subtitles/' + '{}.en.srt'.format(to_srt)
            film = TMDB(movie_file, '***')
            try:
                json_movies.append({'title': film.title, 'original_title': film.ogtitle,
                                    'year': film.year, 'director(s)': film.directors,
                                    'country': film.countries,
                                    'popularity': film.popularity, 'path': movie_file,
                                    'subtitle': srt_file})
            except AttributeError:
                pass

# sort by name
json_movies = sorted(json_movies, key=itemgetter('title'))

with open("film_list.json", "w") as f:
    json.dump(json_movies, f)
