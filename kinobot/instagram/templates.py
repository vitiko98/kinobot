from datetime import datetime
from typing import Dict, Optional

from jinja2 import Template
import timeago

from . import models


def _render_finished(finished: models.FinishedRequest):
    parallel_titles = set([i.parallel_title for i in finished.media_items])

    if len(finished.media_items) == 1 or len(parallel_titles) == 1:
        media = finished.media_items[0]
        pretty = media.pretty_title
        if media.sub_title:
            return f"{pretty}\n{media.sub_title}"

        return pretty

    return " | ".join(parallel_titles)


def _render_request(request: models.Request):
    username = request.user.name
    ago_ = timeago.format(request.added, now=datetime.utcnow())

    return f"Requested by {username} ({request.content}) ({ago_})"


def _hashtags(finished: models.FinishedRequest):
    kgs = set()
    for media in finished.media_items:
        kgs.update(media.keywords)

    return " ".join([f"#{k}" for k in kgs])


def render(finished: models.FinishedRequest, request: models.Request):
    finished_content = _render_finished(finished)
    request_content = _render_request(request)
    hashtags = _hashtags(finished)
    result = f"{finished_content}\n.\n.\n.\n{request_content}"
    return result

    if hashtags:
        return f"{result}\n\n{hashtags}"

    return result
