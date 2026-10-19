import logging
from typing import Any

from app.core.config import Settings, get_settings
from app.core.providers.interfaces import (
    BaseAIProvider,
    BaseCalendarProvider,
    BaseFlightsProvider,
    BaseGmailProvider,
    BasePlacesProvider,
    BaseRoutingProvider,
    BaseServiceProvider,
    BaseWeatherProvider,
)
from app.core.providers.real import (
    RealAIProvider,
    RealCalendarProvider,
    RealFlightsProvider,
    RealGmailProvider,
    RealPlacesProvider,
    RealRoutingProvider,
    RealWeatherProvider,
)
from app.core.providers.simulated import (
    SimulatedAIProvider,
    SimulatedCalendarProvider,
    SimulatedFlightsProvider,
    SimulatedGmailProvider,
    SimulatedPlacesProvider,
    SimulatedRoutingProvider,
    SimulatedWeatherProvider,
)

logger = logging.getLogger("travelmate.providers")


class ProviderRegistry:
    """Registre central des adaptateurs hybrides (choisis par variable d'environnement)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.gmail: BaseGmailProvider = (
            RealGmailProvider(self.settings)
            if self.settings.GMAIL_PROVIDER_MODE == "real"
            else SimulatedGmailProvider(self.settings)
        )
        self.calendar: BaseCalendarProvider = (
            RealCalendarProvider(self.settings)
            if self.settings.CALENDAR_PROVIDER_MODE == "real"
            else SimulatedCalendarProvider(self.settings)
        )
        self.flights: BaseFlightsProvider = (
            RealFlightsProvider(self.settings)
            if self.settings.FLIGHTS_PROVIDER_MODE == "real"
            else SimulatedFlightsProvider(self.settings)
        )
        self.weather: BaseWeatherProvider = (
            RealWeatherProvider(self.settings)
            if self.settings.WEATHER_PROVIDER_MODE == "real"
            else SimulatedWeatherProvider(self.settings)
        )
        self.ai: BaseAIProvider = (
            RealAIProvider(self.settings)
            if self.settings.AI_PROVIDER_MODE == "real"
            else SimulatedAIProvider(self.settings)
        )
        self.places: BasePlacesProvider = (
            RealPlacesProvider(self.settings)
            if self.settings.PLACES_PROVIDER_MODE == "real"
            else SimulatedPlacesProvider(self.settings)
        )
        self.routing: BaseRoutingProvider = (
            RealRoutingProvider(self.settings)
            if self.settings.ROUTING_PROVIDER_MODE == "real"
            else SimulatedRoutingProvider(self.settings)
        )

    def all_providers(self) -> dict[str, BaseServiceProvider]:
        return {
            "gmail": self.gmail,
            "calendar": self.calendar,
            "flights": self.flights,
            "weather": self.weather,
            "ai": self.ai,
            "places": self.places,
        }

    def routing_info(self) -> dict[str, Any]:
        return self.routing.health_info()

    def health_summary(self) -> dict[str, dict[str, Any]]:
        return {name: provider.health_info() for name, provider in self.all_providers().items()}

    def log_active_modes(self) -> list[str]:
        lines: list[str] = []
        logger.info("=== TRAVELMATE HYBRID ADAPTERS STATUS ===")
        for name, provider in self.all_providers().items():
            info = provider.health_info()
            msg = (
                f"[PROVIDER] service={name:<9} | mode={info['mode'].upper():<9} | "
                f"impl={info['implementation']:<26} | env={info['env_var']} | "
                f"credentials_configured={info['credentials_configured']}"
            )
            logger.info(msg)
            lines.append(msg)
        logger.info("=========================================")
        return lines


_DEFAULT_REGISTRY: ProviderRegistry | None = None


def reset_provider_registry() -> None:
    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = None


def get_provider_registry(settings: Settings | None = None) -> ProviderRegistry:
    global _DEFAULT_REGISTRY
    if settings is not None:
        return ProviderRegistry(settings=settings)
    current_settings = get_settings()
    if (
        _DEFAULT_REGISTRY is None
        or _DEFAULT_REGISTRY.settings.AI_PROVIDER_MODE != current_settings.AI_PROVIDER_MODE
        or _DEFAULT_REGISTRY.settings.OLLAMA_BASE_URL != current_settings.OLLAMA_BASE_URL
        or _DEFAULT_REGISTRY.settings.OLLAMA_MODEL != current_settings.OLLAMA_MODEL
    ):
        _DEFAULT_REGISTRY = ProviderRegistry(settings=current_settings)
    return _DEFAULT_REGISTRY

