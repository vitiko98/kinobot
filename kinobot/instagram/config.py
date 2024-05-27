import os
from typing import Dict, List

from dynaconf import Dynaconf
from pydantic import BaseModel
import yaml

settings = Dynaconf(
    envvar_prefix="KINOBOT_IG", settings_files=[os.environ.get("KINOBOT_IG_CONFIG")]
)


class Publisher(BaseModel):
    enabled: bool = False
    handler: str
    constructor: Dict


class Config(BaseModel):
    db_url: str
    ig_client: Dict
    client: Dict
    publishers: List[Publisher] = []

    class Config:
        orm_mode = True

    @classmethod
    def from_yaml(cls, path):
        with open(path, "r") as f:
            data = yaml.safe_load(f.read())

        return cls.parse_obj(data)

    @classmethod
    def default_factory(cls):
        return cls.from_orm(settings)
