from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import os

from api.core.config import settings
from api.routes import incidents_v2, evidence, system, detect, emergency, map as map_routes
from api import db as db_v2


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_v2.init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(incidents_v2.router, prefix=settings.API_V1_STR)
app.include_router(evidence.router, prefix=settings.API_V1_STR)
app.include_router(system.router, prefix=settings.API_V1_STR)
app.include_router(detect.router, prefix=settings.API_V1_STR)
app.include_router(emergency.router, prefix=settings.API_V1_STR)
app.include_router(map_routes.router, prefix=settings.API_V1_STR)

frontend_build = Path(__file__).parent.parent / "frontend" / "build"
if frontend_build.exists():
    # Mount static assets FIRST - before catch-all route
    app.mount("/assets", StaticFiles(directory=frontend_build / "assets"), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # Don't serve frontend for API routes or assets
        if full_path.startswith("api/") or full_path.startswith("assets/"):
            return {"detail": "Not found"}
        index_path = frontend_build / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return {"message": "Frontend not built. Run 'npm run build' in frontend directory."}


@app.get("/")
async def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/api/docs",
        "frontend": "/" if frontend_build.exists() else "not built"
    }