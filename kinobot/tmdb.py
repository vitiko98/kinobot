import sys
import json
import tmdbsimple as tmdb
from guessit import guessit
from fuzzywuzzy import fuzz


# This little function returns cool genre tags from a dictionary of RYM films
def getGenres(movie):
    with open('Certified-Kino-Bot/misc/genres.json') as f:
        data = json.load(f)

    initial = 50
    List = []
    for i in data:
        fuzzy = fuzz.token_sort_ratio(i, movie)
        if fuzzy > initial:
            initial = fuzzy
            List.append(i)

    try:
        return data[List[-1]]['genres']
    except IndexError:
        return False


# guess from filename
def guessfile(movie):
    try:
        guess = guessit(movie, '-s')
    except:
        sys.exit('Guessit error')

    title = guess['title']
    try:
        year = guess['year']
    except KeyError:
        sys.exit('Invalid year. Check {}'.format(movie))
    source = guess.get('source', '')
    return title, year, source


# log movies having trouble with TMDB
def logerror(mov):
    with open("/var/log/kino/kinobot.log", "a") as j:
        j.write(mov)


# get info from tmdb api
class TMDB:
    def __init__(self, movie, token):
        tmdb.API_KEY = token

        self.title, self.year, self.source = guessfile(movie)
        self.countries = []
        self.genres = []
        self.directors = []
        self.similares = []

        search = tmdb.Search()
        search.movie(query=self.title, year=self.year)
        try:
            movieID = search.results[0]['id']
        except KeyError:
            sys.exit(logerror(self.title))

        self.title = search.results[0]['title']
        ogtitle = search.results[0]['original_title']

        if self.title != ogtitle and len(ogtitle) < 45:
            self.title = '{} [{}]'.format(ogtitle, self.title)

        movie = tmdb.Movies(movieID)

        movie.info()
        for m in movie.production_countries:
            self.countries.append(m['name'])

        self.genres = getGenres(self.title)

        if self.genres:
            self.genre_or_country = 'Genre: {}'.format(self.genres)
        else:
            self.genre_or_country = 'Country: {}'.format(', '.join(self.countries))

        movie.credits()
        for m in movie.crew:
            if 'Director' == m['job']:
                self.directors.append(m['name'])
