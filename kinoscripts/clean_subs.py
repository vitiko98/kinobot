#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import sys

# Append the path where the subzero and tld packages (from bazarr) are located.
sys.path.append(os.path.join(os.environ["HOME"], ".local", "other"))


def _update_srt(filename):
    # This import is slow
    from subzero.modification import main  # type: ignore

    subtitle = main.SubtitleModifications(debug=True, language="en")
    subtitle.load(fn=filename)

    og = subtitle.f.to_string("srt")


    subtitle.modify("fix_uppercase", "remove_HI", "common", "remove_tags")
    srt_content = subtitle.f.to_string("srt")

    if len(og) == len(srt_content):
        logging.info("No changes made")
        return

    with open(filename, "w") as f:
        logging.info(f"Writing content to file: {filename}")
        f.write(srt_content)
        logging.info("Ok")


def main():
    try:
        path = sys.argv[1]
    except IndexError:
        sys.exit("Usage: ./clean_sub.py FILE [-f]")

    logging.basicConfig(level=logging.DEBUG)

    if path.endswith(".srt") and os.path.isfile(path):
        _update_srt(path)
    else:
        logging.info("Nothing to do.")


if __name__ == "__main__":
    main()
