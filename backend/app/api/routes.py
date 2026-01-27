from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/market/summary")
async def get_market_summary(request: Request):
    latest = getattr(request.app.state, "latest_snapshot", None)
    if latest is None:
        return JSONResponse({"message": "warming up"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return latest
