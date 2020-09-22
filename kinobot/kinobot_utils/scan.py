import os
import glob

EXTENSIONS = ["*.mkv", "*.mp4", "*.avi"]


def get_list_of_files(path):
    List = []
    for ext in EXTENSIONS:
        for f in glob.glob(os.path.join(path, "**", ext), recursive=True):
            List.append(f)
    return List


class Scan:
    def __init__(self, movie_path, tv_path=None):
        self.movies = get_list_of_files(movie_path)
        if tv_path:
            self.tv_shows = get_list_of_files(tv_path)
