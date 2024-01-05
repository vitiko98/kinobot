import os
from dynaconf import Dynaconf

config = Dynaconf(
    envvar_prefix="KINOBOT", settings_files=[os.environ.get("YAML_CONFIG")]
)
settings = config
