#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Alternative script of extract_subs.sh

import argparse
import json
import os
import shutil
import subprocess
import sys
from tempfile import gettempdir

import asstosrt
from appdirs import user_log_dir

LOG_DIR = user_log_dir("extract_subs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG = os.path.join(LOG_DIR, "log")

parser = argparse.ArgumentParser(description="Extract srt from video.")
parser.add_argument("-v", metavar="VIDEO", help="file")
parser.add_argument("-l", metavar="LANG", help="language", default="en")
parser.add_argument("-f", action="store_true", help="ignore dupes")
args = parser.parse_args()

for command in ("ffprobe", "ffmpeg", "clean_subs.py"):
    if not shutil.which(command):
        sys.exit(f"Command not found {command}")


def _save_log(filename, filesize):
    print("Saving to log file")
    filename_ = filename.split("/")[-1]
    with open(LOG, "a") as f:
        f.write(f"{filename_}\n{filesize}\n")


def _is_dupe(filename, filesize=None) -> bool:
    if args.f:
        return False

    with open(LOG, "r") as f:
        filename_ = filename.split("/")[-1]
        if any(filename_ in line.replace("\n", "").strip() for line in f.readlines()):
            return True
        if filesize:
            return any(
                filesize in line.replace("\n", "").strip() for line in f.readlines()
            )

    return False


def _is_valid(filename) -> bool:
    if not os.path.isfile(filename):
        return False

    with open(filename, "r") as f:
        return len(f.readlines()) > 300


def _get_sub_stream(stdout_dict, codec_name="subrip"):
    return [
        subs.get("index")
        for subs in stdout_dict["streams"]
        if args.l in subs.get("tags", {}).get("language", "n/a")
        and codec_name in subs.get("codec_name", "n/a")
    ]


def _convert_to_srt(temp_file):
    print("Converting ASS sub to SRT")
    with open(temp_file) as ass_:
        try:
            srt_ = asstosrt.convert(ass_)
        # most likely it will work as srt if it fails
        except:  # noqa
            return

        with open(temp_file, "w") as f:
            f.write(srt_)
        print("Ok")


def _extract_subs(filename, filesize, temp_file, srt_file):
    print(f"File {filename} ({filesize})")
    ass_sub = False
    ff_command = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        filename,
    ]
    result = subprocess.run(ff_command, stdout=subprocess.PIPE)

    stdout_dict = json.loads(result.stdout)
    results = _get_sub_stream(stdout_dict)
    if not results:
        print("No srt index found for this file")
        results = _get_sub_stream(stdout_dict, "ass")
        if results:
            ass_sub = True
            print("ASS subtitles found")
        else:
            sys.exit(_save_log(filename, filesize))

    for index in results:
        try:
            extract_command = [
                "ffmpeg",
                "-v",
                "quiet",
                "-stats",
                "-y",
                "-i",
                filename,
                "-map",
                f"0:{index}",
                temp_file,
            ]
            subprocess.run(extract_command, stdout=subprocess.PIPE, timeout=600)
            if ass_sub:
                _convert_to_srt(temp_file)

            if _is_valid(temp_file):
                shutil.move(temp_file, srt_file)
                subprocess.run(["clean_subs.py", srt_file], stdout=subprocess.PIPE)
                break

        except Exception as error:
            print(f"Error extracting subtitle: {error}")

        finally:
            _save_log(filename, filesize)


def main():
    filename = os.path.abspath(args.v)

    if not os.path.isfile(filename):
        sys.exit(f"File doesn't exist: {filename}")

    srt_file = f"{os.path.splitext(filename)[0]}.{args.l}.srt"
    filesize = os.path.getsize(filename)
    temp_file = os.path.join(gettempdir(), f"{filesize}.srt")

    if _is_dupe(filename, filesize):
        sys.exit(f"File already executed: {filename}")

    _extract_subs(filename, filesize, temp_file, srt_file)


if __name__ == "__main__":
    main()
