"""PlantMind API.

Run:  scripts/run_dev.sh   (then open http://127.0.0.1:8000)
Docs: http://127.0.0.1:8000/docs
"""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent.engine import Engine
from api.routers import alerts, assistant, guard, reports, scenarios, telemetry
from core.contracts import CONTRACT_VERSION

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def create_app(autostart: bool = True, engine: Optional[Engine] = None) -> FastAPI:
    engine = engine or Engine()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if autostart:
            engine.start()
        yield
        engine.stop()

    app = FastAPI(title="PlantMind", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine

    @app.get("/api/health")
    def health():
        return {"status": "ok", "contract_version": CONTRACT_VERSION}

    app.include_router(telemetry.router, prefix="/api")
    app.include_router(alerts.router, prefix="/api")
    app.include_router(scenarios.router, prefix="/api")
    app.include_router(guard.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(assistant.router, prefix="/api")

    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(str(WEB_DIR / "index.html"))

    return app


app = create_app()
