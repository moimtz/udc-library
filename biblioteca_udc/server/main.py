"""Biblioteca UDC server entry point.  Run:  python main.py"""
import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

import config
import maintenance
from db import init_db
from routes_library import router as library_router
from routes_users import router as users_router

VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await asyncio.to_thread(maintenance.run_all)
    task = asyncio.create_task(maintenance.loop())
    yield
    task.cancel()


app = FastAPI(title="Biblioteca UDC", version=VERSION, lifespan=lifespan)
app.include_router(users_router)
app.include_router(library_router)


@app.get("/api/health")
def health():
    return {"ok": True, "name": "Biblioteca UDC", "version": VERSION}


@app.get("/")
def root():
    return {"name": "Biblioteca UDC server", "status": "running"}


if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT)
