#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import shutil
import sys

# Append the path where the subzero and tld packages (from bazarr) are located.
sys.path.append(os.path.join(os.environ["HOME"], ".local", "other"))

from subzero.modification import main

logging.basicConfig(level=logging.DEBUG)

try:
    path = sys.argv[1]
except IndexError:
    sys.exit("Usage: ./clean_sub.py {DIR,FILE}")


def get_available_files(path):
    logging.info("Scanning folder")

    available_files = []
    for root, dirs, files in os.walk(path):
        for f in files:
            absolute = os.path.abspath(os.path.join(root, f))
            if absolute.endswith("en.srt") and not os.path.isfile(absolute + ".save"):
                available_files.append(absolute)

    logging.info(f"{len(available_files)} available files found")
    return available_files


def update_srt(filename):
    shutil.copy(filename, filename + ".save")
    subtitle = main.SubtitleModifications(debug=True)
    subtitle.load(fn=filename)
    subtitle.modify("remove_HI", "common", "remove_tags", "fix_uppercase")
    srt_content = subtitle.f.to_string("srt")

    with open(filename, "w") as f:
        logging.info(f"Writing content to file: {filename}")
        f.write(srt_content)
        logging.info("Ok")


if os.path.isfile(path):
    update_srt(path)
elif os.path.isdir(path):
    for filename in get_available_files(path):
        try:
            update_srt(filename)
        except Exception as error:
            logging.error(error, exc_info=True)
else:
    logging.info("Nothing found")
