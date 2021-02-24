class KinoException(Exception):
    " Base class for Kinobot exceptions. "
    pass


class QuoteNotFound(KinoException):
    pass


class MovieNotFound(KinoException):
    pass


class EpisodeNotFound(KinoException):
    pass


class DuplicateRequest(KinoException):
    pass


class OffensiveWord(KinoException):
    pass


class RestingMovie(KinoException):
    pass


class BlockedUser(KinoException):
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


class InconsistentImageSizes(KinoException):
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


class SubtitlesNotFound(KinoException):
    pass


class InexistentTimestamp(KinoException):
    pass


class ImageNotFound(KinoException):
    pass


class NothingFound(KinoException):
    pass


class LimitExceeded(KinoException):
    pass
