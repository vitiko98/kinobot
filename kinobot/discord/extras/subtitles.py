import asyncio
import asyncio.subprocess
import logging
import os
import re
import shutil
import tempfile

from discord.ext import commands
import pysubs2
import requests

from kinobot.media import Episode
from kinobot.media import is_episode
from kinobot.media import Movie

from ..utils import ask
from ..utils import ask_to_confirm
from ..utils import call_with_typing
from ..utils import ExitStatus
from ..utils import on_excs_send

ALASS_PATH = os.environ.get("ALASS_PATH", "alass")


logger = logging.getLogger(__name__)


class SubtitleError(Exception):
    pass


class SubprocessError(SubtitleError):
    pass


async def _ask_for_media(bot, ctx):
    await ctx.send("Tell me the movie or episode")
    response = await ask(bot, ctx)
    if response is None:
        raise ExitStatus

    if is_episode(response):
        media = Episode.from_query(response)
    else:
        media = Movie.from_query(response)

    return media


@on_excs_send((ExitStatus))
async def autosync(bot, ctx: commands.Context):
    media = await _ask_for_media(bot, ctx)
    if not await ask_to_confirm(bot, ctx, f"{media.pretty_title}. Are you sure?"):
        raise ExitStatus

    assert media.path is not None
    subs_path = _subs_from_video(media.path)
    if subs_path is None:
        return await ctx.send("This media item doesn't have any subtitles")

    async def _callback(line):
        if len(line) > 200:
            return None

        await ctx.send(_redact_line(line))

    await automatic_sync(subs_path, media.path, line_callback=_callback)
    await ctx.send("Ok.")


@on_excs_send((ExitStatus))
async def upload(bot, ctx: commands.Context):
    try:
        attachment_url = ctx.message.attachments[0].url
    except IndexError:
        return await ctx.send("No attachment provided")

    loop = asyncio.get_running_loop()
    await ctx.send("Checking SRT file...")

    try:
        subtitles = await call_with_typing(ctx, loop, _download_srt, attachment_url)
    finally:
        await ctx.send("Deleting your attachment...")
        await ctx.message.delete()

    await ctx.send(
        "Check done. Don't forget that you'll be banned forever from this feature if you upload abusive content."
    )

    media = await _ask_for_media(bot, ctx)
    subs_path = _subs_from_video(media.path, check_exists=False)  # type: ignore

    shutil.move(subtitles, subs_path)  # type: ignore
    await ctx.send("Ok.")


@on_excs_send((ExitStatus))
async def edit(bot, ctx: commands.Context):
    media = await _ask_for_media(bot, ctx)

    await ctx.send(
        f"Media item: {media.pretty_title}\n\n"
        "Now tell me the index of the subtitle to edit. ('no to exit)"
    )
    response = await ask(bot, ctx)
    if response is None or response.lower() == "no":
        raise ExitStatus

    try:
        index = int(response) - 1
    except ValueError:
        await ctx.send("Invalid index number.")
        raise ExitStatus

    assert media.path
    subs_path = _subs_from_video(media.path)

    if subs_path is None:
        await ctx.send("This media item doesn't have any subtitles.")
        raise ExitStatus

    subs = pysubs2.load(subs_path)
    line = subs[index]
    await ctx.send(
        f"{line.text}\n\nThis is the line you are gonna edit. Remember: vandalizing "
        "subtitles will get you banned from this feature. Now, type your modification."
    )
    response = await ask(bot, ctx)
    if response is None or response.lower() == "no":
        raise ExitStatus

    if not await ask_to_confirm(bot, ctx, f"{response}\n\nAre you sure? (y/n)"):
        raise ExitStatus

    line.text = response.strip()
    subs[index] = line
    subs.save(subs_path)

    await ctx.send("Saved.")


@on_excs_send((ExitStatus))
async def shift(bot, ctx: commands.Context):
    media = await _ask_for_media(bot, ctx)

    await ctx.send(
        f"Media item: {media.pretty_title}\n\n"
        "Now tell me the offset in milliseconds (it can be negative or positive). "
        "Reply with 'no' to cancel this operation."
    )
    response = await ask(bot, ctx)
    if response is None or response.lower() == "no":
        raise ExitStatus

    try:
        offset = int(response)
    except ValueError:
        await ctx.send("Invalid offset number.")
        raise ExitStatus

    assert media.path is not None

    subs = _subs_from_video(media.path)
    if subs is None:
        await ctx.send("This media item doesn't have any subtitles.")
        raise ExitStatus

    _offset_subtitles(subs, offset)
    await ctx.send("Done.")


def _offset_subtitles(subs_path: str, offset: float, output=None):
    subs = pysubs2.load(subs_path)
    subs.shift(ms=offset)
    output = output or subs_path
    subs.save(output)
    logger.info("Shift of %sms complete for %s", offset, output)


def _subs_from_video(video_path: str, ext=".en.srt", check_exists=True):
    subs = os.path.splitext(video_path)[0] + ext
    if not check_exists:
        return subs

    if os.path.isfile(subs):
        return subs

    return None


async def upload_file(ctx):
    try:
        attachment_url = ctx.message.attachments[0].url
    except IndexError:
        return await ctx.send("No attachment provided")

    _download_srt(attachment_url)


def _download_srt(url):
    response = requests.head(url)
    content_length = int(response.headers.get("content-length", 0))

    mbs = content_length / (1024 * 1024)
    if mbs > 1:
        raise SubtitleError("File is bigger than 1mb. Can't download")

    r = requests.get(url)
    r.raise_for_status()

    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as f:
        f.write(r.content)
        assert pysubs2.load(f.name)
        logger.info("Downloaded: %s", f.name)
        return f.name


async def _readline(stream: asyncio.StreamReader, timeout: float):
    try:
        return await asyncio.wait_for(stream.readuntil(), timeout=timeout)
    except asyncio.exceptions.LimitOverrunError:
        return b""


_FILE_RE = re.compile(r"(/[a-zA-Z\./]*[\s]?)")


def _redact_line(line):
    return _FILE_RE.sub("REDACTED", line)


async def automatic_sync(
    subs_path: str,
    reference_file: str,
    output_file=None,
    line_callback=None,
    timeout=2000,
):
    output_file = output_file or subs_path

    command = [ALASS_PATH, reference_file, subs_path, output_file]
    proc = await asyncio.subprocess.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None

    while True:
        try:
            line = await _readline(proc.stdout, timeout=timeout)
            if proc.returncode is not None and proc.returncode != 0:
                raise SubprocessError

            line = line.decode().strip()

            if line_callback is not None and line:
                await line_callback(line)

        except asyncio.exceptions.IncompleteReadError:
            break
