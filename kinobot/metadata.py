from functools import cached_property
import logging
import sqlite3
from typing import Generator, List, Optional, Tuple, Union

import tmdbsimple as tmdb

from .cache import region
from .constants import TMDB_KEY
from .constants import WEBSITE
from .db import Kinobase
from .db import sql_to_dict
from .exceptions import NothingFound
from .utils import clean_url

tmdb.API_KEY = TMDB_KEY

logger = logging.getLogger(__name__)


class Meta(Kinobase):
    id = None
    image = None
    name = ""
    prefix = "country"
    item_table = "movie_countries"

    __insertables__ = ("id", "name", "image")

    def __init__(self, **kwargs):
        self._set_attrs_to_values(kwargs)

    @property
    def url_clean_title(self) -> str:
        return clean_url(f"{self.name} {self.id}")

    @property
    def web_url(self) -> str:
        return f"{WEBSITE}/{self.prefix}/{self.url_clean_title}"

    @property
    def relative_url(self) -> str:
        return f"/{self.prefix}/{self.url_clean_title}"

    @property
    def markdown_url(self) -> str:
        return f"[{self.name}]({self.web_url})"

    @classmethod
    def from_url(cls, url: str):
        """Parse the ID of an item from Kinobot's website URL format.

        :param url:
        :type url: str
        :raises exceptions.NothingFound
        """
        result = sql_to_dict(
            cls.__database__,
            f"select * from {cls.table} where id=? limit 1",
            (url.upper().split("-")[-1],),
        )
        if result:
            return cls(**result[0])

        raise NothingFound

    def register(self, item_id):
        self._insert()

        self._execute_sql(
            f"insert or ignore into {self.item_table} (movie_id,{self.prefix}_id) values (?,?)",
            (
                item_id,
                self.id,
            ),
        )


class Person(Meta):
    table = "people"
    prefix = "person"
    gender = None
    popularity = 0
    role = None
    category = None

    __insertables__ = ("id", "name", "gender", "popularity", "image", "category")

    def __init__(self, **kwargs):
        super().__init__()

        self._set_attrs_to_values(kwargs)

    def get_movies(self, table: str = "movie", limit: int = 10) -> List[dict]:
        sql = (
            f"select {table}s.*, group_concat({table}_credits.role, ', ') as role "
            f"from {table}_credits inner join {table}s on {table}_credits.{table}_id"
            f"={table}s.id where people_id=? group by {table}s.id limit ?"
        )
        return self._db_command_to_dict(sql, (self.id, limit))

    def update_column(self, column: str):
        self._execute_sql(
            f"update people set {column}=? where id=?",
            (
                getattr(self, column),
                self.id,
            ),
        )

    def __repr__(self) -> str:
        return f"<People {self.name} - {self.role} ({self.id})>"


class Genre(Meta):
    table = "genres"
    prefix = "genre"
    item_table = "movie_genres"

    def __init__(self, **kwargs):
        super().__init__()

        self._set_attrs_to_values(kwargs)

    def get_movies(self) -> List[dict]:
        sql = (
            "select * from movie_genres inner join movies on movie_genres."
            "movie_id = movies.id where genre_id=? order by popularity desc"
        )
        return self._db_command_to_dict(sql, (self.id,))

    def __repr__(self) -> str:
        return f"<Genre {self.name} ({self.id})>"


class TVShowGenre(Meta):
    item_table = "tv_show_genres"

    def register(self, item_id):
        self._insert()

        self._execute_sql(
            f"insert or ignore into {self.item_table} (tv_show_id,genre_id) values (?,?)",
            (
                item_id,
                self.id,
            ),
        )


class Country(Meta):
    table = "countries"
    prefix = "country"
    item_table = "movie_countries"

    def __init__(self, **kwargs):
        kwargs["id"] = kwargs.get("iso_3166_1") or kwargs["id"]
        super().__init__(**kwargs)

    def get_movies(self) -> List[dict]:
        sql = (
            "select * from movie_countries inner join movies on movie_countries."
            "movie_id = movies.id where country_id=? order by popularity desc"
        )
        return self._db_command_to_dict(sql, (self.id,))

    def __repr__(self) -> str:
        return f"<Country {self.name} ({self.id})>"


class Category(Meta):
    table = "categories"
    prefix = "category"
    item_table = "movie_categories"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._registered = False

    def register_for_movie(self, movie_id):
        if not self._registered:
            self.register()
        try:
            self.update_for_movie(movie_id, delete=True)
            self._execute_sql(
                "insert into movie_categories (movie_id,category_id) values (?,?)",
                (movie_id, self.id),
            )
        except sqlite3.IntegrityError:
            logger.debug("Category already registered: %s", self.name)

    @classmethod
    def random_untagged_movie(cls) -> dict:
        sql = (
            "select * from movies where id not in (select movie_id "
            "from movie_categories) order by random() limit 1"
        )
        result = cls()._db_command_to_dict(sql)

        if not result:
            raise NothingFound

        return result[0]

    def update_for_movie(self, movie_id, delete: bool = False):
        if not self._registered:
            self.register()

        if delete:
            self._execute_sql(
                "delete from movie_categories where movie_id=?", (movie_id,)
            )
        else:
            self._execute_sql(
                "update movie_categories set category_id=? where movie_id=?",
                (
                    self.id,
                    movie_id,
                ),
            )

    def register(self):
        params = (self.name.title(),)
        self._execute_sql("insert or ignore into categories (name) values (?)", params)
        res = self._db_command_to_dict("select * from categories where name=?", params)
        self._set_attrs_to_values(res[0])
        self._registered = True

    def get_movies(self) -> List[dict]:
        sql = (
            "select * from movie_categories inner join movies on movie_categories."
            "movie_id = movies.id where category_id=? order by title"
        )
        return self._db_command_to_dict(sql, (self.id,))

    def __repr__(self) -> str:
        return f"<Category {self.name} ({self.id})>"


_JOB_ROLES = (
    "Screenplay",
    "Screenstory",
    "Director of Photography",
    "Director",
    "Producer",
    "Sound Designer",
    "Sound Mixer",
    "Sound Editor",
    "Original Music Composer",
    "Writer",
    "Editor",
    "Novel",
)


class Credits(Kinobase):
    credits_table = "movie_credits"
    column_type_id = "movie_id"

    def __init__(self, people: List[Person], item_id):
        self.people = people
        self.id = item_id

    def get(self, item_id, table: str = "movie"):
        sql = (
            f"select * from {table}_credits inner join people on {table}_credits"
            f".people_id = people.id where {table}_id=?;"
        )
        return self._db_command_to_dict(sql, (item_id,))

    def register(self):
        movie_credits_ = [(person.id, self.id, person.role) for person in self.people]

        people_ = [
            (per.id, per.name, per.gender, per.popularity) for per in self.people
        ]

        self._execute_many(
            "insert or ignore into people (id,name,gender,popularity) values (?,?,?,?)",
            people_,
        )
        self._execute_many(
            f"insert or ignore into {self.credits_table} (people_id,"
            f"{self.column_type_id},role) values (?,?,?)",
            movie_credits_,
        )

    @property
    def directors(self) -> List[Person]:
        return [person for person in self.people if person.role == "Director"]

    @property
    def cast(self) -> List[Person]:
        return [person for person in self.people if person.role not in _JOB_ROLES]

    @property
    def crew(self) -> List[Person]:
        return [person for person in self.people if person.role in _JOB_ROLES]

    @classmethod
    def from_tmdb_id(cls, tmdb_id):
        credits_ = _get_tmdb_credits(tmdb_id)

        crew = [credit for credit in credits_["crew"] if credit["job"] in _JOB_ROLES]

        people = []
        for person in credits_["cast"][:7] + crew:
            role = person.get("character", person.get("job", "n/a"))

            if role is None or "uncredited" in role or not role:  # ""
                continue

            people.append(
                Person(
                    role=role,
                    **person,
                )
            )

        return cls(people, tmdb_id)

    @classmethod
    def from_person_db_list(cls, movie_id, items: List[dict]):
        people = [Person(**item) for item in items]
        return cls(people, movie_id)

    def __repr__(self) -> str:
        return f"<Credits {self.id} ({len(self.people)} people)>"


class EpisodeCredits(Credits):
    credits_table = "episode_credits"
    column_type_id = "episode_id"

    @classmethod
    def from_tmdb_dict(cls, credits_: dict):
        crew = [credit for credit in credits_["crew"] if credit["job"] in _JOB_ROLES]

        people = []
        for person in credits_["guest_stars"][:5] + crew:
            role = person.get("character", person.get("job", "n/a"))

            if role is None or "uncredited" in role or not role:  # ""
                continue

            people.append(
                Person(
                    role=role,
                    **person,
                )
            )

        return cls(people, credits_["id"])


class Metadata(Kinobase):
    prefix: str = "movie"
    id = None

    def _get_foreign(
        self, suffix: str = "credits", table: str = "people", prefix: str = "people"
    ):
        sql = (
            f"select * from {self.prefix}_{suffix} inner join {table} on {self.prefix}_{suffix}"
            f".{prefix}_id = {table}.id where {self.prefix}_id=?;"
        )
        return self._db_command_to_dict(sql, (self.id,))

    def __repr__(self) -> str:
        return f"<Metadata {self.id}>"


class MovieMetadata(Metadata):
    table = "movies"
    prefix: str = "movie"

    def __init__(self, item_id):
        self.id = item_id
        self.position: Optional[int] = None
        self.weighted_rating: Optional[float] = 0
        self._countries: List[Country] = []
        self._categories: List[Category] = []
        self._genres: List[Genre] = []
        self._credits: Union[Credits, None] = None

    @cached_property
    def credits(self) -> Union[Credits, None]:
        credits_ = self._get_foreign()
        if not credits:
            self._load_movie_info_from_tmdb()
            return self._credits

        return Credits.from_person_db_list(self.id, credits_)

    @cached_property
    def rating(self) -> str:
        rating, ratings = self.rating_tuple

        if not ratings or not rating:
            return "No ratings found"

        return f"{round(rating, 2)}/5 from {ratings} ratings"

    @cached_property
    def rating_tuple(self) -> Tuple[float, int]:
        """Return a tuple containing the average and the ratings count.

        :rtype: Tuple[float, int]
        """
        sql = (
            "select avg(movie_ratings.rating), count() from movie_ratings "
            "where rated_movie=?"
        )
        rating, ratings = self._fetch(sql, (self.id,))

        if not ratings or rating is None:
            return 0, 0

        return round(rating, 2), ratings

    @cached_property
    def countries(self) -> List[Country]:
        countries = self._get_foreign("countries", "countries", "country")
        if not countries:
            self._load_movie_info_from_tmdb()
            return self._countries

        return [Country(**item) for item in countries]

    @cached_property
    def genres(self) -> List[Genre]:
        genres = self._get_foreign("genres", "genres", "genre")
        if not genres:
            self._load_movie_info_from_tmdb()
            return self._genres

        return [Genre(**item) for item in genres]

    @cached_property
    def categories(self) -> List[Category]:
        genres = self._get_foreign("categories", "categories", "category")
        return [Category(**item) for item in genres]

    @property
    def embed_fields(self) -> Generator[dict, None, None]:
        for meta in (self.genres, self.countries, self.categories):  # type: ignore
            if meta:
                yield {
                    "name": meta[0].table.title(),
                    "value": ", ".join([item.markdown_url for item in meta]),
                }

    @property
    def request_title(self) -> str:
        text = []

        if self.credits.directors:
            dirs = ", ".join(item.name for item in self.credits.directors)
            text.append(f"Director: {dirs}")

        # if self.categories:
        #    cats = ", ".join(item.name for item in self.categories)
        #    text.append(f"Category: {cats}")

        return "\n".join(text)

    def load_and_register(self):
        self._load_movie_info_from_tmdb()

        logger.info("Registering metadata in the database")
        for item in self._genres + self._countries + self._categories:  # type: ignore
            item.register(self.id)

        self._credits = Credits.from_tmdb_id(self.id)
        self._credits.register()

    def _load_movie_info_from_tmdb(self):
        logger.debug("Falling back to TMDB to get metadata")
        movie = get_tmdb_movie(self.id)

        self._countries = [
            Country(**item) for item in movie.get("production_countries")
        ]
        self._genres = [Genre(**item) for item in movie.get("genres")]


class EpisodeMetadata(Metadata):
    table = "episodes"
    prefix = "episode"

    def __init__(self, episode_id, metadata: Optional[dict] = None):
        self.id = episode_id
        self._credits: Union[Credits, None] = None

        if metadata:
            self._credits = EpisodeCredits.from_tmdb_dict(metadata)

    @cached_property
    def credits(self) -> Union[Credits, None]:
        if not self._credits:
            self._credits = EpisodeCredits.from_person_db_list(
                self.id, self._get_foreign()
            )
        return self._credits

    @property
    def request_title(self) -> str:
        text = []

        if self.credits.directors:
            dirs = ", ".join(item.name for item in self.credits.directors)
            text.append(f"Director: {dirs}")

        return "\n".join(text)

    def load_and_register(self):
        self._credits.register()


class EpisodeMetadataDummy(EpisodeMetadata):
    @cached_property
    def credits(self) -> Union[Credits, None]:
        return EpisodeCredits([], self.id)

    @property
    def request_title(self) -> str:
        return ""

    def load_and_register(self):
        pass


@region.cache_on_arguments()
def _get_tmdb_credits(movie_id: int) -> dict:
    movie = tmdb.Movies(movie_id)
    return movie.credits()


@region.cache_on_arguments()
def get_tmdb_movie(movie_id: int) -> dict:
    movie = tmdb.Movies(movie_id)
    return movie.info()
