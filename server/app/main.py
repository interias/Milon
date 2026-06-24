"""FastAPI-App. Mountet Router (folgen inkrementell) und legt beim Start das Schema an."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import coach, ingest, metrics, progress
from .api import settings as settings_api
from .config import PROGRESS_DIR, settings
from .db import init_db
from .sync import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start_scheduler()
    yield
    scheduler.shutdown_scheduler()


app = FastAPI(title="Milon API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # localhost + private LAN-IPs (RFC1918) auf jedem Port — damit der Zugriff vom Handy
    # im Heim-WLAN (http://192.168.x.x:3000 → Backend :8000) erlaubt ist. Lokale App.
    allow_origin_regex=(
        r"http://(localhost|127\.0\.0\.1|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?"
    ),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "timezone": settings.timezone}


app.include_router(ingest.router)
app.include_router(metrics.router)
app.include_router(coach.router)
app.include_router(progress.router)
app.include_router(settings_api.router)

# Statische Auslieferung der Fortschritts-Fotos
app.mount("/media/progress", StaticFiles(directory=str(PROGRESS_DIR)), name="progress-media")

# Noch offen (folgt): das Next.js-Frontend (client/) im Klar-&-Klinisch-Design.
