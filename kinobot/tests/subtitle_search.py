import subs
import os
import sys

movie = subs.search_movie(os.environ.get("MOVIE_JSON"), sys.argv[1])
subtitles = subs.get_subtitle(movie)

results = subs.get_complete_quote(subtitles, sys.argv[2])
print(results)
