import os
from typing import Any, Dict, Optional

import pydantic
from pydantic import BaseModel
from pydantic import parse_obj_as
import yaml


class ImageTransporterConfig(BaseModel):
    name: str
    config: Dict[str, Any]


class ServicesConfig(BaseModel):
    default_image_transporter: ImageTransporterConfig


class RestConfig(BaseModel):
    port: int = 16047
    host: str = "127.0.0.1"
    log_level: str = "info"
    workers: Optional[int] = 1
    log_config: Optional[str] = None
    reload: bool = False


class Config(BaseModel):
    services: ServicesConfig
    rest: RestConfig


class ConfigError(Exception):
    pass


def load(config_path=None):
    """env var: KINOBOT_SERVER_CONFIG
    raises ConfigError"""
    path = config_path or os.environ.get("KINOBOT_SERVER_CONFIG")
    if not path:
        raise ConfigError(
            "No config path was set. Use KINOBOT_SERVER_CONFIG or pass a config_path parameter"
        )

    try:
        with open(path, "r") as f:
            config_dict = yaml.safe_load(f)
    except Exception as error:
        raise ConfigError(f"Error reading file: {error}") from error

    try:
        return parse_obj_as(Config, config_dict)
    except pydantic.ValidationError as error:
        raise ConfigError(f"Error parsing config: {error}") from error


def test_load(s) -> Config:
    return s
