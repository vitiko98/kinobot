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
        self.file = file
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
        result = search.results[0]
        movieID = result["id"]

        self.title = result["title"]
        self.popularity = result["popularity"]
        self.ogtitle = result["original_title"]
        poster = result["poster_path"] if result["poster_path"] else "Unknown"
        backdrop = result["backdrop_path"] if result["backdrop_path"] else "Unknown"
        self.poster = "https://image.tmdb.org/t/p/original" + poster
        self.backdrop = "https://image.tmdb.org/t/p/original" + backdrop

        if self.title != self.ogtitle and len(self.ogtitle) < 45:
            self.pretty_title = "{} [{}]".format(self.ogtitle, self.title)
        else:
            self.pretty_title = self.title

        movie = tmdb.Movies(movieID)

        movie.info()
        self.country_list = ", ".join([m["name"] for m in movie.production_countries])
        self.countries = "Country: {}".format(self.country_list)

        movie.credits()
        for m in movie.crew:
            if "Director" == m["job"]:
                self.directors.append(m["name"])
        self.directors = ", ".join(self.directors)
