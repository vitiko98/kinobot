#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Alternative script of extract_subs.sh

import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys

LOGS = os.path.join(os.environ["HOME"], ".extracted_subs.log")
KINOBASE = os.environ["KINOBASE"]


def get_movies_from_db():
    with sqlite3.connect(KINOBASE) as conn:
        return conn.execute(
            "select path from movies where cast(popularity as Integer) > 14"
        ).fetchall()


def save_log(filename, filesize):
    print("Saving to log file")

    with open(LOGS, "a") as f:
        f.write(f"{filename}\n{filesize}\n")

    with sqlite3.connect(KINOBASE) as conn:
        conn.execute(
            "update movies set og_sub=1 where path=?",
            (filename,),
        )
        conn.commit()


def is_dupe(filename, filesize=None):
    with open(LOGS, "r") as f:
        if any(filename in line.replace("\n", "").strip() for line in f.readlines()):
            return True
        if filesize:
            if any(
                filesize in line.replace("\n", "").strip() for line in f.readlines()
            ):
                return True


def is_valid(filename):
    if not os.path.isfile(filename):
        return

    with open(filename, "r") as f:
        if len(f.readlines()) > 100:
            return True


def extract_subs(filename, filesize, temp_file, srt_file):
    print(f"File {filename} ({filesize})")
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

    results = [
        subs.get("index")
        for subs in json.loads(result.stdout)["streams"]
        if "en" in subs.get("tags", {}).get("language", "n/a")
        and "subrip" in subs.get("codec_name", "n/a")
    ]
    if not results:
        print("No index found for this file")
        sys.exit(save_log(filename, filesize))

    for index in results:
        try:
            extract_command = [
                "ffmpeg",
                "-y",
                "-i",
                filename,
                "-map",
                f"0:{index}",
                temp_file,
            ]
            subprocess.run(extract_command, stdout=subprocess.PIPE, timeout=600)
            if is_valid(temp_file):
                shutil.move(temp_file, srt_file)
                shutil.copy(srt_file, srt_file + ".save")
                subprocess.run(["clean_subs.py", srt_file], stdout=subprocess.PIPE)
        except Exception as error:
            print(f"Error extracting subtitle: {error}")
        finally:
            save_log(filename, filesize)


try:
    filename = sys.argv[1]
except IndexError:
    filenames = get_movies_from_db()
    random.shuffle(filenames)
    filename = None

    for i in filenames:
        if not is_dupe(i[0]):
            filename = i[0]
            break

    if not filename:
        sys.exit("DB query is empty")

if not os.path.isfile(filename):
    sys.exit(f"File doesn't exist: {filename}")

srt_file = os.path.split(filename)[0] + ".en.srt"
filesize = os.path.getsize(filename)
temp_file = os.path.join("/tmp", f"{filesize}.srt")

if is_dupe(filename, filesize):
    sys.exit(f"File already executed: {filename}")

extract_subs(filename, filesize, temp_file, srt_file)
