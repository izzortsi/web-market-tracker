from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter()


def _get_processor(request: Request):
    return getattr(request.app.state, "processor", None)


@router.get("/api/market/summary")
async def get_market_summary(request: Request):
    processor = _get_processor(request)
    if processor is None:
        return JSONResponse({"message": "warming up"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return {
        "global": processor.get_global_series(),
        "promoted": processor.get_promoted(),
    }


@router.get("/api/global/metrics")
async def get_global_metrics(request: Request):
    processor = _get_processor(request)
    if processor is None:
        return JSONResponse({"message": "warming up"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return {"series": processor.get_global_series()}


@router.get("/api/screener/candidates")
async def get_candidates(request: Request):
    processor = _get_processor(request)
    if processor is None:
        return JSONResponse({"message": "warming up"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return {"candidates": processor.get_candidates()}


@router.get("/api/screener/promoted")
async def get_promoted(request: Request):
    processor = _get_processor(request)
    if processor is None:
        return JSONResponse({"message": "warming up"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return {"promoted": processor.get_promoted()}


@router.get("/api/symbols/{symbol}")
async def get_symbol_state(symbol: str, request: Request):
    processor = _get_processor(request)
    if processor is None:
        return JSONResponse({"message": "warming up"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    state = processor.get_symbol_state(symbol)
    if state is None:
        if processor.is_promoted(symbol):
            return JSONResponse({"message": "warming up"}, status_code=status.HTTP_202_ACCEPTED)
        return JSONResponse({"message": "not tracked"}, status_code=status.HTTP_404_NOT_FOUND)
    return state
