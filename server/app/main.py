"""FastAPI-App. Mountet Router (folgen inkrementell) und legt beim Start das Schema an."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import checkins, circumferences, coach, garmin_routes, ingest, metrics, progress, run_zones, sleep
from .api import settings as settings_api
from .api import garmin_activity, garmin_daily, recovery_analysis, run_insights, source_status
from .api import body_progress, coach_actions, run_context, run_reference
from .api import garmin_nights, route_atlas, run_mechanics, weekly_journal
from .api import sync_inventory, overview_history, route_segments
from .config import DATA_DIR, PROGRESS_DIR, settings
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
app.include_router(coach_actions.router)
app.include_router(coach.router)
app.include_router(progress.router)
app.include_router(settings_api.router)
app.include_router(checkins.router)
app.include_router(sleep.router)
app.include_router(run_zones.router)
app.include_router(circumferences.router)
app.include_router(garmin_routes.router)
app.include_router(garmin_activity.router)
app.include_router(garmin_daily.router)
app.include_router(run_insights.router)
app.include_router(recovery_analysis.router)
app.include_router(source_status.router)
app.include_router(body_progress.router)
app.include_router(run_context.router)
app.include_router(run_reference.router)
app.include_router(garmin_nights.router)
app.include_router(route_atlas.router)
app.include_router(run_mechanics.router)
app.include_router(weekly_journal.router)
app.include_router(sync_inventory.router)
app.include_router(overview_history.router)
app.include_router(route_segments.router)

# Statische Auslieferung der Fortschritts-Fotos
app.mount("/media/progress", StaticFiles(directory=str(PROGRESS_DIR)), name="progress-media")
COACH_IMAGES_DIR = DATA_DIR / "coach-images"
COACH_IMAGES_DIR.mkdir(exist_ok=True)
app.mount("/media/coach-images", StaticFiles(directory=str(COACH_IMAGES_DIR)), name="coach-images")

# Noch offen (folgt): das Next.js-Frontend (client/) im Klar-&-Klinisch-Design.
