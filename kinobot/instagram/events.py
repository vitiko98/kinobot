from datetime import datetime
from typing import Optional

import pydantic

from . import models


class Event(pydantic.BaseModel):
    timestamp = datetime.utcnow()


class PostCreated(Event):
    finished_request: models.FinishedRequest
    request: models.Request
    ig_id: str
    caption: Optional[str] = None
    permalink: Optional[str] = None
