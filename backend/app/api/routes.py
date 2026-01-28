from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/market/summary")
async def get_market_summary(request: Request):
    processor = getattr(request.app.state, "processor", None)
    if processor is None:
        return JSONResponse({"message": "warming up"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return processor.get_snapshot()
