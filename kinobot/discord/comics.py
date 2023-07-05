import asyncio
import logging
import os
import shutil
import tempfile

from discord.ext import commands
from libgenmics import client as libgen
from libgenmics import comicinfo
from libgenmics import comicvine
from libgenmics import zipping
import requests

from kinobot.sources.comics import client as kvt_client
from kinobot.utils import get_yaml_config

from .utils import ask
from .utils import ask_to_confirm
from .utils import call_with_typing
from .utils import paginated_list

logger = logging.getLogger(__name__)


def _pretty_print(l):
    return f"{l.title} [{l.issue}] [{l.size}]"


def _cv_pretty_print(issue: comicvine.ComicIssue):
    return f"{issue.volume.name} [Issue #{issue.issue_number}]"


async def curate(bot, ctx: commands.Context, query, bytes_callback=None, config=None):
    config = config or get_yaml_config(os.environ["YAML_CONFIG"], "comics")

    client = libgen.Client()

    loop = asyncio.get_event_loop()
    results = await call_with_typing(ctx, loop, client.search, query)

    if not results:
        await ctx.send("No results.")

    item = await paginated_list(
        bot, ctx, f"Results for `{query}`", results, _pretty_print
    )
    if item is None:
        return None

    if not item.bytes:
        await ctx.send("Unknown size. Couldn't continue.")
        return None

    if bytes_callback is not None and bytes_callback(item.bytes) is False:
        await ctx.send("You don't have enough GBs to continue.")
        return None

    await ctx.send(
        f"**{_pretty_print(item)}**"
        "\n\nPlease give me the ComicVine URL of the issue so I can add tags correctly."
    )

    url = await ask(bot, ctx, timeout=600)
    if not url:
        return None

    cv_client = comicvine.Client(config["comicvine"]["api_key"])

    try:
        cv_issue = await call_with_typing(
            ctx, loop, cv_client.issue, url.strip()
        )  # type: comicvine.ComicIssue
    except requests.HTTPError:
        await ctx.send("Invalid URL.")
        return None

    correct = await ask_to_confirm(
        bot,
        ctx,
        f"Tagging\n{_pretty_print(item)}\n->\n{_cv_pretty_print(cv_issue)}\n\nIs this correct? (y/n)",
    )
    if not correct:
        await ctx.send("Bye.")
        return None

    await ctx.send("Import queued. Please wait.")
    await loop.run_in_executor(None, _download, item, cv_issue, config["root_dir"])
    await ctx.reply("Import finished successfully! Updating library...")

    kvt_client_ = await call_with_typing(
        ctx, loop, kvt_client.Client.from_config
    )  # type: kvt_client.Client
    await call_with_typing(ctx, loop, kvt_client_.scan_all)

    await ctx.send("Ok.")

    return item


def _download(item, cv_issue, root_dir):
    with tempfile.NamedTemporaryFile(prefix=__name__) as temp_f:
        _safe_download(item.mirrors, temp_f.name)

        with tempfile.NamedTemporaryFile(prefix=__name__, suffix=".cbz") as temp_f_2:
            _extract_and_zip(temp_f.name, cv_issue, temp_f_2.name)

            logger.debug("OK: %s", temp_f_2.name)

            parent_dir = os.path.join(root_dir, cv_issue.volume.name)
            logger.debug("Parent dir: %s", parent_dir)
            os.makedirs(parent_dir, exist_ok=True)

            final_path = os.path.join(parent_dir, f"{cv_issue.issue_number}.cbz")
            shutil.copy(temp_f_2.name, final_path)
            logger.debug("Final path: %s", final_path)


def _safe_download(url, output, chunk_size=8192):
    logger.debug("Downloading %s to %s", url, output)
    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(output, "wb") as file:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                file.write(chunk)


def _extract_and_zip(zipped, cv_issue: comicvine.ComicIssue, output_file):
    with tempfile.TemporaryDirectory(prefix=__name__) as temp_d:
        zipping.extract(zipped, temp_d)
        comicinfo.make(
            os.path.join(temp_d, "ComicInfo.xml"), **cv_issue.to_comic_info_xml_params()
        )
        zipping.make_cbz(temp_d, output_file)


async def explorecomics(bot, ctx: commands.Context, *args):
    query = " ".join(args)
    query = kvt_client.ComicQuery.from_str(query)
    client = kvt_client.Client.from_config()
    if not query.title:
        return await ctx.send("No title provided")

    loop = asyncio.get_running_loop()

    item = await call_with_typing(
        ctx, loop, None, client.first_series_matching, query.title
    )
    if not item:
        return await ctx.send(
            "Comic not found in db.\n\nNote that library updates are made every 15 minutes."
        )

    if not item.chapters:
        return await ctx.send("This comic doesn't have any issues.")

    rec = f"""The issues shown above are available to request. You may get the page numbers to request
by your own mediums - be it physical copies, e-readers, or digital platforms.

Request example: {item.name} issue X page X !comic [0:0]"""
    issues = ", ".join([chapter.number for chapter in item.chapters])[:1000]
    await ctx.send(f"**Title:** {item.name}\n**Issues:** {issues}\n\n*{rec}*")
