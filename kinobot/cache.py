#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import os

from dogpile.cache import make_region

from .constants import CACHE_DIR

MEDIA_LIST_TIME = datetime.timedelta(hours=1).total_seconds()
PATREON_MEMBERS_TIME = datetime.timedelta(minutes=10).total_seconds()
TOP_TIME = MEDIA_LIST_TIME  # Temporary

os.makedirs(CACHE_DIR, exist_ok=True)

region = make_region().configure(
    "dogpile.cache.dbm",
    arguments={"filename": os.path.join(CACHE_DIR, "cache.db")},
)
