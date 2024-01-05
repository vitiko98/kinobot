import base64
import logging
import os
import shutil
import sqlite3
import tempfile
from typing import Callable, List, Optional

from babelfish import Language
from cleanit import Config
from cleanit import Subtitle
from deluge_client import DelugeRPCClient
import fese
from fese.exceptions import UnsupportedCodec
from pydantic import BaseModel

from kinobot.config import settings
from kinobot.constants import KINOBASE

logger = logging.getLogger(__name__)


class Torrent(BaseModel):
    id: str
    name: str
    save_path: Optional[str] = None
    total_remaining: int = 0

    def hash(self):
        return hash(id)

    @property
    def complete_path(self):
        if self.save_path is None:
            return ""

        path = os.path.join(self.save_path, self.name)
        return _replace_path(path, *settings.anime.mapping)


def _replace_path(path, new, old):
    relative = os.path.relpath(path, old)
    return os.path.join(new, relative)


def register_torrent(torrent_id, name, table="anime_torrents"):
    with sqlite3.connect(KINOBASE) as conn:
        try:
            conn.execute(
                f"insert into {table} (torrent_id,name) values (?,?)",
                (torrent_id, name),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            logger.info("Already added")


def get_torrents(table="anime_torrents"):
    with sqlite3.connect(KINOBASE) as conn:
        items = conn.execute(
            f"select * from {table}",
        ).fetchall()
        return [Torrent(id=i[0], name=i[1]) for i in items]


class Client:
    def __init__(self, host, port, username, password) -> None:
        self._client = DelugeRPCClient(host, port, username, password, decode_utf8=True)
        self._client.connect()

    @classmethod
    def from_config(cls):
        return cls(
            settings.deluge.host,
            settings.deluge.port,
            settings.deluge.username,
            settings.deluge.password,
        )

    def add_torrent_file(self, filename: str):
        with open(filename, "rb") as torrent_file:
            file_contents = torrent_file.read()
            encoded_file_contents = base64.b64encode(file_contents).decode("utf-8")

        torrent_id = self._client.call(
            "core.add_torrent_file", filename, encoded_file_contents, {}
        )
        return torrent_id

    def get_finished_torrents(self):
        deluge_torrents = self._client.call(
            "core.get_torrents_status",
            {},
            ["name", "hash", "save_path", "total_remaining"],
        )
        items = []
        for item in deluge_torrents.values():  # type: ignore
            if item["total_remaining"] != 0:
                continue

            items.append(Torrent(id=item["hash"], **item))

        return items


def _get_files(path):
    files_in_folder = []
    for root, dirs, files in os.walk(path):
        for file in files:
            file_path = os.path.join(root, file)
            files_in_folder.append(file_path)

    return files_in_folder


def hl_torrent(stored: Torrent, live: Torrent):
    folder = os.path.join(settings.anime.folder, stored.name)
    os.makedirs(folder, exist_ok=True)
    logger.debug("Folder: %s [%s]", folder, live.complete_path)

    if os.path.isfile(live.complete_path):
        try:
            os.link(
                live.complete_path,
                os.path.join(folder, os.path.basename(live.complete_path)),
            )
            logger.debug("Link created: %s -> %s", live.complete_path, folder)
        except FileExistsError:
            pass

    elif os.path.isdir(live.complete_path):
        files = _get_files(live.complete_path)
        for file in files:
            try:
                os.link(file, os.path.join(folder, os.path.basename(file)))
                logger.debug("Link created: %s -> %s", file, folder)
            except FileExistsError:
                pass
    else:
        logger.debug("Folder not found")


def handle_torrents(client: Client, stored: List[Torrent], handle_callback: Callable):
    for torrent in client.get_finished_torrents():
        for stored_torrent in stored:
            if torrent.id == stored_torrent.id:
                logger.debug("Found matching torrent")
                handle_callback(stored_torrent, torrent)


def _clean_sub(path):
    sub = Subtitle(path)

    cfg = Config()
    rules = cfg.select_rules(tags={"no-sdh", "no-style"})

    if sub.clean(rules):
        sub.save()


def _find_subs(path, language):
    basename = os.path.splitext(path)[0]
    sub = f"{basename}.{language}.srt"
    if os.path.exists(sub):
        return sub


def handle_downloaded():
    client = Client.from_config()
    handle_torrents(client, get_torrents(), hl_torrent)


def scan_subs():
    for file in _get_files(settings.anime.folder):
        if file.endswith(("mkv", "mp4")):
            extract_subtitles(file, "en")


def extract_subtitles(path, language):
    found_sub = _find_subs(path, language)

    if found_sub:
        logger.info("%s already has subtitles", path)
        return None

    container = fese.container.FFprobeVideoContainer(path)
    language_ = Language.fromietf(language)
    subs = container.get_subtitles()

    def _filter(s):
        return s.language == language_ and (
            (s.disposition.generic or s.disposition.hearing_impaired)
            and not (s.disposition.karaoke or s.disposition.lyrics)
        )

    subs = list(filter(_filter, subs))
    used_langs = []

    def _sort(s):
        try:
            return s.tags.number_of_frames or 0
        except:
            return 0

    subs = sorted(subs, key=_sort, reverse=True)

    items = {}

    for sub in subs:
        if sub.language in used_langs:
            continue
        try:
            items = container.extract_subtitles(
                [sub],
                overwrite=True,
                custom_dir=tempfile.gettempdir(),
                convert_format="srt",
            )
        except UnsupportedCodec:
            pass

        used_langs.append(sub.language)
        items.update(items)

    if not items:
        logger.debug("No subtitles found")
        return None

    subtitle = list(items.values())[0]

    _clean_sub(subtitle)

    new_subtitle_path = f"{os.path.splitext(path)[0]}.{language}.srt"
    shutil.move(subtitle, new_subtitle_path)
    logger.info("Moved: %s -> %s", subtitle, new_subtitle_path)
