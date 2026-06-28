"""FastAPI entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import settings
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.trongrid_api_key:
        raise RuntimeError(
            "TRONGRID_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    init_db()
    yield


app = FastAPI(title="trontrace", version="0.1.0", lifespan=lifespan)

# Local-only tool: the frontend dev server runs on :3000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
