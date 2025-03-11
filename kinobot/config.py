import os

from dynaconf import Dynaconf


_CONFIG = os.environ.get("YAML_CONFIG", "config.yml")

print(f"YAML config: {_CONFIG} (exists: {os.path.exists(_CONFIG or '')})")

config = Dynaconf(envvar_prefix="KINOBOT", settings_files=[_CONFIG])
settings = config

PATH = _CONFIG
