import os
import sqlite3
from operator import itemgetter
from pathlib import Path


def get_complete_list():
    with sqlite3.connect(os.environ.get("KINOBASE")) as conn:
        cursor = conn.execute("SELECT * from MOVIES")
        return get_dicts_from_db(cursor)


def get_dicts_from_db(cursor):
    dict_list = []
    for i in cursor:
        if i[5] == "Blacklist" or not i[8]:
            continue
        to_srt = Path(i[8]).with_suffix("")
        srt = "{}.{}".format(to_srt, "en.srt")
        srt_split = srt.split("/")
        srt_relative_path = os.path.join(srt_split[-2], srt_split[-1])
        dict_list.append(
            {
                "title": i[0],
                "original_title": i[1],
                "year": i[2],
                "director": i[3],
                "country": i[4],
                "category": i[5],
                "poster": i[6],
                "backdrop": i[7],
                "path": i[8],
                "subtitle": srt,
                "subtitle_relative": srt_relative_path,
                "subtitle_relative_2": os.path.join(
                    os.environ["HOME"], "subs", srt_relative_path
                ),
                "tmdb": i[10],
                "overview": i[11],
                "popularity": float(i[12]),
                "budget": int(i[13]),
                "source": i[14],
                "runtime": i[16],
                "requests": i[17],
                "last_request": i[18],
            }
        )
    return sorted(dict_list, key=itemgetter("title"))


def get_emoji_from_countries(country_list):
    # Assuming these movies are from what now is Russia or CR
    country_list = [
        i.replace("Soviet Union", "Russia").replace("Czechoslovakia", "Czech Republic")
        for i in country_list
    ]
    country_list = sorted(set(country_list), key=country_list.index)  # remove dupes
    standard_names = coco.convert(country_list, to="ISO2")
    new_country_list = (
        standard_names if isinstance(standard_names, list) else [standard_names]
    )
    return "".join([flag.flag(country_code) for country_code in new_country_list])
