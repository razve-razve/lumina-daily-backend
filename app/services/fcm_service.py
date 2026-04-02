"""Firebase Cloud Messaging — sends daily push notification to user devices."""
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_firebase_app = None


def _get_firebase_app():
    global _firebase_app
    if _firebase_app is None:
        import firebase_admin
        from firebase_admin import credentials
        cred = credentials.Certificate(settings.firebase_credentials_path)
        _firebase_app = firebase_admin.initialize_app(cred)
    return _firebase_app


async def send_daily_notification(fcm_token: str, language: str) -> bool:
    """Send 'your guidance is ready' push notification. Returns True on success."""
    if not fcm_token:
        return False

    messages = {
        "en": ("Your daily guidance is ready ✨", "Open Lumina Daily to read your stars."),
        "ru": ("Ваш ежедневный прогноз готов ✨", "Откройте Lumina Daily, чтобы узнать, что говорят звёзды."),
    }
    title, body = messages.get(language, messages["en"])

    try:
        from firebase_admin import messaging
        _get_firebase_app()
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            token=fcm_token,
        )
        messaging.send(message)
        return True
    except Exception as e:
        logger.warning(f"FCM send failed for token {fcm_token[:20]}...: {e}")
        return False
