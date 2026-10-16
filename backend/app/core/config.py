from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderMode = Literal["simulated", "real"]

_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
_LOCAL_ENV = Path(__file__).resolve().parents[2] / ".env"
_ENV_FILES = tuple(str(p) for p in (_ROOT_ENV, _LOCAL_ENV) if p.exists()) or (".env",)


class Settings(BaseSettings):
    """Configuration centrale chargée exclusivement depuis les variables d'environnement / .env."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Général ---
    APP_NAME: str = "TravelMate"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"

    # --- Base de données ---
    POSTGRES_USER: str = Field(default="travelmate")
    POSTGRES_PASSWORD: str = Field(default="")
    POSTGRES_DB: str = Field(default="travelmate_db")
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./travelmate.db")
    DATABASE_URL_SYNC: str = Field(default="sqlite:///./travelmate.db")

    # --- Redis ---
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # --- Sécurité & Chiffrement ---
    JWT_SECRET_KEY: str = Field(default="")
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=1440)
    VAULT_MASTER_KEY: str = Field(default="")

    # --- Modes des Adaptateurs Hybrides (simulated | real) ---
    GMAIL_PROVIDER_MODE: ProviderMode = Field(default="simulated")
    GOOGLE_CLIENT_ID: str = Field(default="")
    GOOGLE_CLIENT_SECRET: str = Field(default="")
    GOOGLE_REDIRECT_URI: str = Field(default="http://localhost:8000/api/v1/auth/google/callback")
    GMAIL_SENDER_EMAIL: str = Field(default="noreply@travelmate.local")

    CALENDAR_PROVIDER_MODE: ProviderMode = Field(default="simulated")
    GOOGLE_CALENDAR_API_KEY: str = Field(default="")

    FLIGHTS_PROVIDER_MODE: ProviderMode = Field(default="simulated")
    AMADEUS_CLIENT_ID: str = Field(default="")
    AMADEUS_CLIENT_SECRET: str = Field(default="")
    AMADEUS_BASE_URL: str = Field(default="https://test.api.amadeus.com")

    WEATHER_PROVIDER_MODE: ProviderMode = Field(default="simulated")
    WEATHER_API_KEY: str = Field(default="")
    WEATHER_BASE_URL: str = Field(default="https://api.openweathermap.org/data/2.5")
    WEATHER_FORECAST_HORIZON_DAYS: int = Field(default=90, ge=1)

    AI_PROVIDER_MODE: ProviderMode = Field(default="simulated")
    AI_API_KEY: str = Field(default="")
    AI_MODEL_NAME: str = Field(default="gemini-2.5-flash")

    PLACES_PROVIDER_MODE: ProviderMode = Field(default="simulated")
    GOOGLE_PLACES_API_KEY: str = Field(default="")
    MAPBOX_ACCESS_TOKEN: str = Field(default="")

    ROUTING_PROVIDER_MODE: ProviderMode = Field(default="simulated")
    OPENROUTESERVICE_API_KEY: str = Field(default="")
    OPENROUTESERVICE_BASE_URL: str = Field(default="https://api.openrouteservice.org")
    GOOGLE_DIRECTIONS_API_KEY: str = Field(default="")

    # --- Fenêtre de visite du séjour (tampons configurables après arrivée et avant départ) ---
    TRIP_ARRIVAL_BUFFER_HOURS: float = Field(default=2.0, ge=0.0)
    TRIP_DEPARTURE_BUFFER_HOURS: float = Field(default=3.0, ge=0.0)

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
