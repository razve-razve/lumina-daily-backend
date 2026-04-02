from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str
    supabase_url: str = "https://gacucpygzpximyxjmied.supabase.co"
    supabase_jwt_secret: str = ""  # Optional — used as fallback for legacy tokens

    # Cache
    redis_url: str = "redis://localhost:6379"

    # External APIs
    google_places_api_key: str
    timezonedb_api_key: str
    openai_api_key: str

    # Firebase (path to service account JSON file)
    firebase_credentials_path: str = "firebase-credentials.json"

    # RevenueCat webhook shared secret
    revenuecat_webhook_secret: str = ""

    # Ephemeris
    ephe_path: str = "/app/ephe"

    # App
    environment: str = "production"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()
