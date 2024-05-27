from sqlalchemy.ext.declarative import declarative_base

from alembic import command
from alembic.config import Config

Base = declarative_base()


def setup_database(alembic_cfg_path, revision="head"):
    alembic_cfg = Config(alembic_cfg_path)
    command.upgrade(alembic_cfg, revision)
