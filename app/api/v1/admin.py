from fastapi import APIRouter, Header, HTTPException

from app.config import settings
from app.core.batch_job import run_daily_batch

router = APIRouter()


@router.post("/run-batch")
async def trigger_batch(x_admin_secret: str = Header(...)):
    """Manually trigger the daily batch job. Protected by admin secret."""
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    import asyncio
    asyncio.create_task(run_daily_batch())
    return {"status": "batch job started"}
