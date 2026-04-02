"""
RevenueCat webhook — updates subscription_status when a user buys or cancels.
RevenueCat sends a POST with an Authorization header containing our shared secret.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.repositories.user_repository import get_user_by_id, update_user
from app.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# RevenueCat event types that mean the user has an active paid subscription
_ACTIVE_EVENTS = {
    "INITIAL_PURCHASE",
    "RENEWAL",
    "PRODUCT_CHANGE",
    "UNCANCELLATION",
}

# RevenueCat event types that mean the subscription has ended
_INACTIVE_EVENTS = {
    "EXPIRATION",
    "CANCELLATION",
    "BILLING_ISSUE",
    "SUBSCRIBER_ALIAS",
}


def _new_status(event_type: str) -> Optional[str]:
    if event_type in _ACTIVE_EVENTS:
        return "active"
    if event_type in _INACTIVE_EVENTS:
        return "free"
    return None  # ignore other event types


@router.post("/revenuecat", status_code=status.HTTP_200_OK)
async def revenuecat_webhook(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    # Verify the shared secret RevenueCat sends in the Authorization header
    if not settings.revenuecat_webhook_secret:
        logger.warning("REVENUECAT_WEBHOOK_SECRET not set — rejecting request")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook not configured")

    if authorization != settings.revenuecat_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

    body = await request.json()
    event = body.get("event", {})
    event_type = event.get("type", "")
    # RevenueCat sends the Supabase user UUID as app_user_id
    app_user_id = event.get("app_user_id", "")

    new_status = _new_status(event_type)
    if new_status is None:
        logger.info(f"Ignoring RevenueCat event type: {event_type}")
        return {"received": True}

    if not app_user_id:
        logger.warning("RevenueCat webhook missing app_user_id")
        return {"received": True}

    try:
        user = await get_user_by_id(db, app_user_id)
    except Exception:
        logger.warning(f"Invalid app_user_id format: {app_user_id}")
        return {"received": True}

    if not user:
        logger.warning(f"RevenueCat webhook: user {app_user_id} not found in DB")
        return {"received": True}

    user.subscription_status = new_status
    await update_user(db, user)
    logger.info(f"User {app_user_id} subscription_status → {new_status} (event: {event_type})")
    return {"received": True}
