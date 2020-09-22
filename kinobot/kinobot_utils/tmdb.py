import os
import tmdbsimple as tmdb
from guessit import guessit

TMDB_KEY = os.environ.get("TMDB")


# guess from filename
def guessfile(movie):
    guess = guessit(movie, "-s")

    if guess["type"] == "episode":
        title = guess["title"].title()
        try:
            season = "S{:02}".format(guess["season"])
            episode = "E{:02}".format(guess["episode"])
            return title, season, episode
        except KeyError:
            return
    else:
        try:
            title = guess["title"]
            year = guess["year"]
            return title, year
        except KeyError:
            return


# get info from tmdb api
class TMDB:
    def __init__(self, file):
        try:
            try:
                self.title, self.year = guessfile(file)
                self.is_movie = True
                self.get_movie_info()
            except TypeError:
                return
        except ValueError:
            self.title, self.season, self.episode = guessfile(file)
            self.is_movie = False
            self.get_tv_info()

    def get_tv_info(self):
        self.title = self.title
        self.season = self.season
        self.episode = self.episode

    def get_movie_info(self):
        tmdb.API_KEY = TMDB_KEY
        self.countries = []
        self.genres = []
        self.directors = []
        self.similares = []

        search = tmdb.Search()
        search.movie(query=self.title, year=self.year)
        try:
            movieID = search.results[0]["id"]
        except IndexError:
            return
        self.title = search.results[0]["title"]
        self.popularity = search.results[0]["popularity"]
        self.ogtitle = search.results[0]["original_title"]
        self.poster = (
            "https://image.tmdb.org/t/p/original" + search.results[0]["poster_path"]
        )

        if self.title != self.ogtitle and len(self.ogtitle) < 45:
            self.pretty_title = "{} [{}]".format(self.ogtitle, self.title)
        else:
            self.pretty_title = self.title

        movie = tmdb.Movies(movieID)

        movie.info()
        for m in movie.production_countries:
            self.countries.append(m["name"])
        self.countries = ", ".join(self.countries)

        self.countries = "Country: {}".format(self.countries)

        movie.credits()
        for m in movie.crew:
            if "Director" == m["job"]:
                self.directors.append(m["name"])
        self.directors = ", ".join(self.directors)
