from typing import List

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Security
from fastapi.security.api_key import APIKeyQuery

from .services import Bracket, FinishedRequest
from .services import ImageTransporter
from .services import media_search
from .services import MediaItem
from .services import process_request as p_r
from .services import Subtitle
from .services import subtitle_search

router = APIRouter()

_api_key_query = APIKeyQuery(name="api_key")


def get_api_key():
    raise NotImplementedError


def get_transporter():
    raise NotImplementedError


def check_api_key(api_key_query=Security(_api_key_query), api_key=Depends(get_api_key)):
    if api_key and api_key == api_key_query:
        return True

    raise HTTPException(status_code=403, detail="Ivalid API Key")


@router.get("/request")
async def process_request(
    content: str,
    transporter: ImageTransporter = Depends(get_transporter),
    api_key=Depends(check_api_key),
) -> FinishedRequest:
    assert api_key

    return p_r(content, transporter)


@router.get("/mediasearch")
async def mediasearch(
    query: str,
    api_key=Depends(check_api_key),
) -> List[MediaItem]:
    assert api_key

    return media_search(query)


@router.get("/bracket")
async def bracket(
    id: int,
    query: str,
    api_key=Depends(check_api_key),
) -> List[Bracket]:
    assert api_key

    return subtitle_search(str(id), query)
