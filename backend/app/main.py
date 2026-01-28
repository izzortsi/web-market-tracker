from fastapi import FastAPI

from .api.routes import router
from .services.processor import ProcessorService

app = FastAPI()
app.include_router(router)


@app.on_event("startup")
async def on_startup() -> None:
    processor = ProcessorService()
    processor.start()
    app.state.processor = processor


@app.on_event("shutdown")
async def on_shutdown() -> None:
    processor = getattr(app.state, "processor", None)
    if processor:
        processor.stop()
