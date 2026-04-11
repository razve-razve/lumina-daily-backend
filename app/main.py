import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.api.v1 import admin, advice, auth, location, profile, settings, timezone, webhooks
from app.core.batch_job import run_daily_batch
from app.core.ephemeris import init_ephemeris
from app.db.session import engine
from app.services.redis_service import close_redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_ephemeris()
    scheduler.add_job(run_daily_batch, "cron", hour=2, minute=0, id="daily_batch")
    scheduler.start()
    logger.info("Scheduler started — daily batch runs at 02:00 UTC")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    await close_redis()
    await engine.dispose()


app = FastAPI(
    title="Lumina Daily API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.include_router(auth.router,     prefix="/api/v1/auth",     tags=["auth"])
app.include_router(profile.router,  prefix="/api/v1/profile",  tags=["profile"])
app.include_router(advice.router,   prefix="/api/v1/advice",   tags=["advice"])
app.include_router(location.router, prefix="/api/v1/location", tags=["location"])
app.include_router(timezone.router, prefix="/api/v1/timezone", tags=["timezone"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(admin.router,    prefix="/api/v1/admin",    tags=["admin"])


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
