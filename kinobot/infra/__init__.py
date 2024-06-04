from typing import Callable, Optional, Type
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import functools


from kinobot.exceptions import KinoException
from kinobot.config import config


def maker():
    engine = create_engine(config.infra.sqlalchemy_url)
    return sessionmaker(bind=engine)


class DuplicateError(KinoException):
    pass


def translate_exc(
    exc_cls: Type[Exception],
    output_exc_cls: Type[Exception] = KinoException,
    checker: Optional[Callable] = None,
    output_maker: Optional[Callable] = None,
):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exc_cls as e:
                if checker is not None:
                    if checker(e):
                        raise output_exc_cls((output_maker or str)(e)) from e
                else:
                    raise

        return wrapper

    return decorator
