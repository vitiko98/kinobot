import logging
import sys

import click

from kinobot.comments import collect
from kinobot.config import KINOLOG
from kinobot.db import update_library
from kinobot.post import post

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(module)s.%(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(KINOLOG), logging.StreamHandler()],
)


@click.group()
def cli():
    pass


cli.add_command(collect)
cli.add_command(update_library)
cli.add_command(post)

if __name__ == "__main__":
    sys.exit(cli())
