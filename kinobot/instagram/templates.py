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
        if len(pretty.split("\n")) == 1:
            title = media.simple_title
            if media.sub_title:
                title = f"{title}\n{media.sub_title}"
            return title
        else:
            return pretty

    return " | ".join(parallel_titles)


def _render_request(request: models.Request):
    username = request.user.name
    ago_ = timeago.format(request.added, now=datetime.utcnow())

    return f"Requested by {username} ({request.content}) ({ago_})"


def render(finished: models.FinishedRequest, request: models.Request):
    finished_content = _render_finished(finished)
    request_content = _render_request(request)
    return f"{finished_content}\n.\n.\n{request_content}"
