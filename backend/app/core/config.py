from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "IMS - Incident Management System"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # PostgreSQL
    POSTGRES_DSN: str = "postgresql://postgres:postgres@localhost:5432/ims_db"

    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "ims_raw"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Ingestion queue
    SIGNAL_QUEUE_MAXSIZE: int = 50_000
    SIGNAL_WORKER_CONCURRENCY: int = 20
    DEBOUNCE_WINDOW_SECONDS: int = 10

    # Rate limiting
    RATE_LIMIT_GLOBAL: int = 10_000
    RATE_LIMIT_PER_IP: int = 500
    RATE_LIMIT_WINDOW_SECONDS: int = 10


settings = Settings()
