#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from discord import Embed


class KinoException(Exception):
    'Base class for "public" exceptions.'

    @property
    def embed(self) -> Embed:
        """Discord embed containing the exception info.

        :rtype: Embed
        """
        title = f"{type(self).__name__} exception raised!"
        return Embed(title=title, description=str(self)[:200])


class KinoUnwantedException(KinoException):
    "Base class for exceptions that require attention."


class SubtitlesNotFound(KinoUnwantedException):
    pass


class TempUnavailable(KinoException):
    pass


class QuoteNotFound(KinoException):
    pass


class MovieNotFound(KinoException):
    pass


class EpisodeNotFound(KinoException):
    pass


class FailedQuery(KinoException):
    pass


class DuplicateRequest(KinoException):
    pass


class OffensiveWord(KinoException):
    pass


class RestingMovie(KinoException):
    pass


class TooShortQuery(KinoException):
    pass


class BadKeywords(KinoException):
    pass


class TooLongRequest(KinoException):
    pass


class InvalidRequest(KinoException):
    pass


class DifferentSource(KinoException):
    pass


class NotAvailableForCommand(KinoException):
    pass


class InconsistentSubtitleChain(KinoException):
    pass


class ChainRequest(KinoException):
    pass


class NotEnoughColors(KinoException):
    pass


class NSFWContent(KinoException):
    pass


class InexistentTimestamp(KinoException):
    pass


class ImageNotFound(KinoException):
    pass


class NothingFound(KinoException):
    pass


class LimitExceeded(KinoException):
    pass


class DiscordAccountNotLinked(KinoException):
    pass


class RecentPostFound(KinoUnwantedException):
    pass


class FrameTimeoutExpired(KinoUnwantedException):
    pass
