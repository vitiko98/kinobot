#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import sys

# Append the path where the subzero and tld packages (from bazarr) are located.
sys.path.append(os.path.join(os.environ["HOME"], ".local", "other"))

from subzero.modification import main

logging.basicConfig(level=logging.INFO)

LOGS = os.path.join(os.environ["HOME"], "logs", "clean_subs.log")

try:
    path = sys.argv[1]
except IndexError:
    sys.exit("Usage: ./clean_sub.py FILE")


def save_log(filename):
    print("Saving to log file")
    filename_ = os.path.basename(filename)
    with open(LOGS, "a") as f:
        f.write(f"{filename_}\n")


def is_dupe(filename):
    with open(LOGS, "r") as f:
        filename_ = os.path.basename(filename)
        if any(filename_ in line.replace("\n", "").strip() for line in f.readlines()):
            logging.info(f"Duplicate file: {filename_}")
            return True


def update_srt(filename):
    subtitle = main.SubtitleModifications(debug=False)
    subtitle.load(fn=filename)
    subtitle.modify("remove_HI", "common", "remove_tags", "fix_uppercase")
    srt_content = subtitle.f.to_string("srt")

    with open(filename, "w") as f:
        logging.info(f"Writing content to file: {filename}")
        f.write(srt_content)
        logging.info("Ok")
        save_log(filename)


if path.endswith(".srt") and os.path.isfile(path) and not is_dupe(path):
    update_srt(path)
else:
    logging.info("Nothing to do.")
