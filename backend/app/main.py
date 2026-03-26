"""
O2C Intelligence — FastAPI application entry point.

Architecture:
  - FastAPI with CORS middleware (allow all origins for dev/demo)
  - Single router mounted at /api
  - Static frontend served from /frontend/build in production
  - Graceful 503 if database has not been initialised yet
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.api.routes import router

# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="O2C Graph API",
    version="1.0.0",
    description="Order-to-Cash graph system with LLM-powered natural-language query interface",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(router, prefix="/api")

# ── Serve React build in production ──────────────────────────────────────────
# When SERVE_FRONTEND=true, serve the React build from ../frontend/build
SERVE_FRONTEND = os.getenv("SERVE_FRONTEND", "false").lower() == "true"
FRONTEND_BUILD = Path(__file__).resolve().parent.parent.parent / "frontend" / "build"

if SERVE_FRONTEND and FRONTEND_BUILD.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_BUILD), html=True), name="static")

# ── Exception handlers ────────────────────────────────────────────────────────

@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    return JSONResponse(
        status_code=503,
        content={
            "error": str(exc),
            "hint": "Run: cd backend && python scripts/etl.py",
        },
    )


# ── Root endpoints ────────────────────────────────────────────────────────────

@app.get("/", tags=["Meta"])
def root():
    return {
        "status": "ok",
        "message": "O2C Graph API is running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Meta"])
def health():
    """Liveness + readiness check."""
    from app.db.connection import DB_PATH
    db_ready = Path(DB_PATH).exists() if DB_PATH else False
    return {
        "status": "healthy" if db_ready else "degraded",
        "db_ready": db_ready,
        "db_path": str(DB_PATH),
        "hint": None if db_ready else "Run: cd backend && python scripts/etl.py",
    }
