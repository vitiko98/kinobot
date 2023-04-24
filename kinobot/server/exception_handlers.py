from typing import Callable, Dict, Type

from fastapi import Response
from fastapi import status

from kinobot import exceptions


async def _handle_kino_exceptions(request, exc: Exception):
    return Response(
        content=f"{type(exc).__name__} raised: {exc}",
        status_code=status.HTTP_400_BAD_REQUEST,
    )


async def _handle_unwanted_exceptions(request, exc: Exception):
    return Response(
        content=f"Unwanted error! PLEASE REPORT THIS. {type(exc).__name__} raised: {exc} ",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


async def _handle_nothing_found(request, exc: Exception):
    return Response(
        content=f"{type(exc).__name__} raised: {exc}",
        status_code=status.HTTP_404_NOT_FOUND,
    )


registry = {
    exceptions.KinoException: _handle_kino_exceptions,
    exceptions.NothingFound: _handle_nothing_found,
    Exception: _handle_unwanted_exceptions,
}  # type: Dict[Type[Exception], Callable]
