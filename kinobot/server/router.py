from fastapi import APIRouter
from fastapi import Depends

from .builders import get_transporter
from .services import FinishedRequest
from .services import ImageTransporter
from .services import process_request as p_r

router = APIRouter()


@router.get("/request")
async def process_request(
    content: str, transporter: ImageTransporter = Depends(get_transporter)
) -> FinishedRequest:
    return p_r(content, transporter)
