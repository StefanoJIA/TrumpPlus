from functools import lru_cache
import os

from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://daily_truth:daily_truth@localhost:5432/daily_truth_brief",
    )
    app_env: str = os.getenv("APP_ENV", "local")


@lru_cache
def get_settings() -> Settings:
    return Settings()

