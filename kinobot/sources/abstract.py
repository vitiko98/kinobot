# -*- coding: utf-8 -*-


import datetime
from abc import ABC
from abc import abstractclassmethod
from abc import abstractmethod
from abc import abstractproperty

from kinobot import exceptions


class AbstractMedia(ABC):
    type = None
    path = None

    @abstractclassmethod
    def from_request(cls, query: str):
        raise NotImplementedError

    @abstractproperty
    def id(self):
        raise NotImplementedError

    @abstractproperty
    def pretty_title(self) -> str:
        raise NotImplementedError

    @abstractproperty
    def markdown_url(self) -> str:
        raise NotImplementedError

    @abstractproperty
    def simple_title(self) -> str:
        raise NotImplementedError

    @abstractproperty
    def parallel_title(self) -> str:
        raise NotImplementedError

    @abstractproperty
    def metadata(self):
        return None

    @property
    def keywords(self):
        return []

    @abstractclassmethod
    def from_id(cls, id_):
        raise NotImplementedError

    @abstractclassmethod
    def from_query(cls, query: str):
        raise NotImplementedError

    def get_subtitles(self, *args, **kwargs):
        raise exceptions.InvalidRequest("Quotes not supported for this media")

    def dump(self):
        raise exceptions.InvalidRequest("Dump not supported for this media format")

    @abstractmethod
    def get_frame(self, timestamps):
        raise NotImplementedError

    def register_post(self, post_id):
        pass

    def age(self) -> datetime.datetime:
        return datetime.datetime.now()

    def __eq__(self, __value: object) -> bool:
        if isinstance(__value, AbstractMedia) and self.path is not None:
            return self.path == __value.path

        return super().__eq__(__value)
