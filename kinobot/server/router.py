from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Security
from fastapi.security.api_key import APIKeyQuery

from .services import FinishedRequest
from .services import ImageTransporter
from .services import process_request as p_r

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
