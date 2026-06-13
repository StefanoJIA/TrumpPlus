from uuid import uuid4

from fastapi import FastAPI, Request

from app.api.routes import router
from app.core.environment import validate_startup_environment
from app.core.request_context import set_request_id


validate_startup_environment()

app = FastAPI(
    title="Daily Truth Brief",
    description="Neutral, source-backed brief generator for public political social media signals.",
    version="0.1.0",
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    set_request_id(request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(router)
