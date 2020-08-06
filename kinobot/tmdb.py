import sys
import tmdbsimple as tmdb
from guessit import guessit

# guess from filename
def guessfile(movie):
    try:
        guess = guessit(movie, '-s')
    except:
        sys.exit('Guessit error')

    title = guess['title']
    try:
        year = guess['year']
    except:
        sys.exit('Invalid year. Check {}'.format(movie))
    source = guess.get('source', '')
    return title, year, source

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
        except:
            sys.exit('TMDB error searching {}'.format(self.title))

        self.title = search.results[0]['title']
        ogtitle = search.results[0]['original_title']
        if self.title != ogtitle:
            self.title = '{} AKA {}'.format(ogtitle, self.title)
        self.overview = search.results[0]['overview']

        movie = tmdb.Movies(movieID)

        movie.info()
        for m in movie.production_countries:
            self.countries.append(m['name'])

        for m in movie.genres:
            self.genres.append(m['name'])

        movie.credits()
        for m in movie.crew:
            if 'Director' == m['job']:
                self.directors.append(m['name'])

        movie.similar_movies()
        for m in movie.results:
            self.similares.append(m['title'])
