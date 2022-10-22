import logging
from typing import Any, Callable, Dict, Set, Tuple, Optional

import pydantic
import yaml

# from ..frame import PostProc

logger = logging.getLogger(__name__)

PostProc = None

_checker_registry: Dict[str, Callable] = {}


def checker(name: str):
    def real_decorator(f):
        _checker_registry[name] = f
        return f

    return real_decorator


def _checker(value: Any, pp: PostProc):
    pass


@checker("fonts")
def _fonts_checker(value: Any, pp: PostProc):
    found = pp.font in value
    logger.debug("Font found? %s [%s -> %s]", found, pp.font, value)
    return found


@checker("aspect_quotient_ranges")
def _aspect_quotient_ranges_checker(value: Any, pp: PostProc):
    frame_size = pp.frame.pil.size
    a_quotient = frame_size[0] / frame_size[1]
    logger.debug("Aspect quotient: %s", a_quotient)
    met = False

    for range_ in value:
        logger.debug("Checking range: %s", range_)
        a, b = range_
        if min(a, b) <= a_quotient <= max(a, b):
            met = True
            logger.debug("Range met [%s -> %s]", a_quotient, range_)
            break
        else:
            logger.debug("Range not met")

    return met


@checker("text_len_ranges")
def _text_len_ranges_checker(value: Any, pp: PostProc):
    text = pp.frame.message
    if text is None:
        text_len = 0
    else:
        text_len = len(text)

    logger.debug("Text length: %s", text_len)
    met = False

    for range_ in value:
        logger.debug("Checking range: %s", range_)
        a, b = range_
        if min(a, b) <= text_len <= max(a, b):
            met = True
            logger.debug("Range met [%s -> %s]", text_len, range_)
            break
        else:
            logger.debug("Range not met")

    return met


@checker("exclude_if_set")
def _exclude_if_set_checker(value: Any, pp: PostProc):
    keys_set = set(pp.og_dict.keys())
    for key in value:
        if key in keys_set:
            logger.debug("%s is already set: %s. Can't apply", key, keys_set)
            return False

    return True


@checker("frame_count_ranges")
def _frame_count_ranges_checker(value: Any, pp: PostProc):
    frame_count = pp.context.get("frame_count")
    if frame_count is None:
        logger.debug("Frame count not found in context. Returning True")
        return True

    logger.debug("Frame count: %s", frame_count)
    met = False

    for range_ in value:
        logger.debug("Checking range: %s", range_)
        a, b = range_
        if min(a, b) <= frame_count <= max(a, b):
            met = True
            logger.debug("Range met [%s -> %s]", frame_count, range_)
            break
        else:
            logger.debug("Range not met")

    return met


class Requirements(pydantic.BaseModel):
    fonts: Set[str] = set()
    aspect_quotient_ranges: Set[Tuple[float, float]] = set()
    text_len_ranges: Set[Tuple[float, float]] = set()
    frame_count_ranges: Set[Tuple[float, float]] = set()
    exclude_if_set: Set[str] = set()


class Profile(pydantic.BaseModel):
    name: str
    description: Optional[str] = None
    requirements: Requirements = Requirements()
    apply: Dict[str, Any] = {}

    @classmethod
    def from_yaml_file(cls, path):
        with open(path, "r") as f:
            data = yaml.safe_load(f)

        profiles = []
        for profile, content in data.items():
            if not isinstance(content, dict):
                continue

            content = {k: v for k, v in content.items() if v is not None}
            clean_reqs = {
                k: v
                for k, v in content.get("requirements", {}).items()
                if v is not None
            }
            content["requirements"] = clean_reqs

            try:
                profile = cls(name=profile, **content)
                profiles.append(profile)
            except Exception as error:
                logger.error("'%s' error loading [%s] profile", error, content)
            else:
                logger.debug("%s loaded succesfuly", profile)

        return profiles

    def _run_checkers(self, pp: PostProc):
        instance_dict = self.requirements.dict()
        met = False
        mets = []

        for key, checker in _checker_registry.items():
            logger.debug("Running checker: %s", key)
            instance_value = instance_dict.get(key)
            if not instance_value:
                logger.debug(
                    "Falsy value for '%s': '%s'. Ignoring", key, instance_value
                )
                continue

            met = checker(instance_value, pp)
            mets.append(met)

            logger.debug("%s met? %s: %s", key, met, instance_value)
            if not met:
                logger.debug("Requirement not met. Breaking loop")
                break

        verdict = False not in mets
        logger.debug("Verdict for checkers: %s", verdict)
        return verdict

    def _apply(self, pp: PostProc):
        # Make a copy with the validated values
        new = pp.copy(self.apply).dict()

        if not self.apply:
            logger.debug("Nothing to apply")
            return None

        for key, val in self.apply.items():
            logger.debug("Applying: %s: %s", key, new[key])
            setattr(pp, key, new[key])

        return None

    def visit(self, pp: PostProc):
        logger.debug("Running checkers for %s", self)

        should_apply = self._run_checkers(pp)
        if should_apply:
            logger.debug("Applying %s", self)
            self._apply(pp)
        else:
            logger.debug("Not applying %s", self)

    def __str__(self) -> str:
        return f"<Profile '{self.name}' [Description: {self.description}]>"
