from datetime import timedelta
import logging
from typing import Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel
import yaml

logger = logging.getLogger(__name__)


class Frame(BaseModel):
    dimensions: Tuple[int, int]
    postproc: Dict
    text: Optional[str]
    timestamp: timedelta
    media_uri: str


class RequestTrace(BaseModel):
    postproc: Dict
    command: str
    single_image: bool
    frames: List[Frame]


class Checker:
    _config = None

    def __call__(self, request_trace: RequestTrace) -> bool:
        raise NotImplementedError

    def __str__(self) -> str:
        return f"<{self.__class__.__name__}: {self._config}>"


class Config(BaseModel):
    pass


class CheckerConfig(BaseModel):
    handler: Checker
    name: str = ""
    description: str = ""

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def from_yaml_file(cls, path):
        with open(path, "r") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, list):
            raise ValueError("yaml content isnt' a list.")

        items = []
        for item in data:
            if "handler" not in item:
                logger.info("Handler not set: %s", item)
                continue

            handler_cls = _checker_registry.get(item["handler"])
            if handler_cls is None:
                logger.info(
                    "%s not found in registry: %s", item["handler"], _checker_registry
                )
                continue

            try:
                handler = handler_cls(**item["constructor"])
            except Exception as error:
                logger.error("Couldn't initialize %s: %s", item, error)
                continue

            items.append(
                cls(
                    handler=handler,
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                )
            )

        return items


def get_not_passed(request_trace: RequestTrace, checker_configs: List[CheckerConfig]):
    not_passed = []  # type: List[CheckerConfig]

    for checker_config in checker_configs:
        callback = checker_config.handler
        logger.debug("Running: %s", callback)
        if not callback(request_trace):
            logger.debug("Check not passed")
            not_passed.append(checker_config)
        else:
            logger.debug("OK")

    return not_passed


_checker_registry: Dict[str, Type[Checker]] = {}


def checker(name: str):
    def real_decorator(c):
        _checker_registry[name] = c
        return c

    return real_decorator


@checker("text_lines")
class BasicTextLinesChecker(Checker):
    def __init__(self, min_lines: int, delimiter="\n") -> None:
        self._min_lines = min_lines
        self._delimiter = delimiter

    def __call__(self, request_trace: RequestTrace) -> bool:
        for frame in request_trace.frames:
            if frame.text is None:
                continue

            lines = len(frame.text.split(self._delimiter))
            if lines > self._min_lines:
                logger.debug("Offending line found: %s", frame.text)
                return False

        logger.debug("No offending lines found")
        return True


@checker("stroke")
class BasicStrokeChecker(Checker):
    def __init__(self, min_stroke_width=0, min_text_shadow_stroke=0) -> None:
        self._min_stroke_width = min_stroke_width
        self._min_stroke_shadow = min_text_shadow_stroke

    def __call__(self, request_trace: RequestTrace) -> bool:
        if request_trace.postproc.get("stroke_width", 0) > self._min_stroke_width:
            logger.debug("Offending stroke: %s", request_trace.postproc["stroke_width"])
            return False

        if request_trace.postproc.get("text_shadow_stroke", 0) > self._min_stroke_width:
            logger.debug(
                "Offending stroke: %s", request_trace.postproc["text_shadow_stroke"]
            )
            return False

        for frame in request_trace.frames:
            if frame.postproc.get("stroke_width", 0) > self._min_stroke_width:
                logger.debug("Offending stroke: %s", frame.postproc["stroke_width"])
                return False

            if frame.postproc.get("text_shadow_stroke", 0) > self._min_stroke_width:
                logger.debug(
                    "Offending stroke: %s", frame.postproc["text_shadow_stroke"]
                )
                return False

        logger.debug("No offending frames found")
        return True


@checker("dimensions_raw")
class DimensionsRawChecker(Checker):
    def __init__(self, dimension_strs) -> None:
        self._dimenstion_strs = set(dimension_strs)

    def __call__(self, request_trace: RequestTrace) -> bool:
        dimensions_raw = request_trace.postproc.get("og_dict", {}).get("dimensions")
        if not dimensions_raw:
            logger.debug("No dimensions requested")
            return True

        dimensions_raw = dimensions_raw.strip()
        for dimension_str in self._dimenstion_strs:
            dimension_str = dimension_str.strip()
            if dimension_str == dimensions_raw:
                logger.debug("Offending dimension: %s", dimension_str)
                return False

        return True


@checker("was_key_requested")
class WasKeyRequestedChecker(Checker):
    def __init__(self, keys) -> None:
        self._keys = set(keys)

    def __call__(self, request_trace: RequestTrace) -> bool:
        og_dicts = [request_trace.postproc.get("og_dict", {})]
        og_dicts.extend(
            [frame.postproc.get("og_dict", {}) for frame in request_trace.frames]
        )

        for og_dict in og_dicts:
            for key in self._keys:
                if key in og_dict:
                    logger.debug("%s was requested: %s", key, og_dict)
                    return False

        return True
