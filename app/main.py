from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.include_router(router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
