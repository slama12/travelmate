from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any

from app.core.config import ProviderMode


class CityNotSimulatedError(ValueError):
    """Levée lorsqu'une ville n'est pas présente dans le catalogue simulé et que le mode est 'simulated'."""

    def __init__(self, city_name: str) -> None:
        self.city_name = city_name
        super().__init__(
            f"Ville '{city_name}' non disponible en simulation. "
            "Aucune donnée inventée n'est générée : activez PLACES_PROVIDER_MODE=real pour interroger l'API réelle."
        )


class BaseServiceProvider(ABC):
    """Interface socle commune à tous les adaptateurs de services externes."""

    service_name: str
    env_var_name: str
    mode: ProviderMode

    @abstractmethod
    def has_credentials(self) -> bool:
        """Indique si les clés/secrets requis sont présents dans .env."""

    def health_info(self) -> dict[str, Any]:
        return {
            "service": self.service_name,
            "mode": self.mode,
            "implementation": self.__class__.__name__,
            "env_var": self.env_var_name,
            "credentials_configured": self.has_credentials(),
            "status": "ready" if (self.mode == "simulated" or self.has_credentials()) else "missing_credentials",
        }


class BaseGmailProvider(BaseServiceProvider, ABC):
    service_name = "gmail"
    env_var_name = "GMAIL_PROVIDER_MODE"

    @abstractmethod
    async def send_booking_confirmation(
        self,
        recipient_email: str,
        passenger_name: str,
        pnr: str,
        origin_iata: str,
        destination_iata: str,
        departure_at: datetime,
        return_at: datetime,
        price_eur: float,
    ) -> dict[str, Any]:
        """Envoie l'e-mail de confirmation de réservation de billet d'avion."""


class BaseCalendarProvider(BaseServiceProvider, ABC):
    service_name = "calendar"
    env_var_name = "CALENDAR_PROVIDER_MODE"

    @abstractmethod
    async def create_visit_event(
        self,
        calendar_id: str,
        title: str,
        location_name: str,
        start_at: datetime,
        end_at: datetime,
        description: str = "",
        timezone_name: str = "UTC",
    ) -> dict[str, Any]:
        """Crée un événement de visite dans Google Calendar."""

    @abstractmethod
    async def update_visit_event(
        self,
        calendar_id: str,
        event_id: str,
        title: str,
        location_name: str,
        start_at: datetime,
        end_at: datetime,
        description: str = "",
        timezone_name: str = "UTC",
    ) -> dict[str, Any]:
        """Met à jour un événement de visite existant dans Google Calendar."""

    @abstractmethod
    async def delete_visit_event(
        self,
        calendar_id: str,
        event_id: str,
    ) -> dict[str, Any]:
        """Supprime un événement de visite dans Google Calendar."""


class BaseFlightsProvider(BaseServiceProvider, ABC):
    service_name = "flights"
    env_var_name = "FLIGHTS_PROVIDER_MODE"

    @abstractmethod
    async def search_flights(
        self,
        origin_iata: str,
        destination_iata: str,
        departure_date: date,
        return_date: date,
        travel_style: str = "STANDARD",
    ) -> list[dict[str, Any]]:
        """Recherche des vols aller-retour réalistes selon le mode (ECONOMIC, STANDARD, LUXURY)."""


class BaseWeatherProvider(BaseServiceProvider, ABC):
    service_name = "weather"
    env_var_name = "WEATHER_PROVIDER_MODE"

    @abstractmethod
    async def get_daily_forecast(
        self,
        city_name: str,
        latitude: float,
        longitude: float,
        start_date: date,
        days: int = 5,
    ) -> list[dict[str, Any]]:
        """Retourne les prévisions météo journalières avec indicateur de pluie."""


class BaseAIProvider(BaseServiceProvider, ABC):
    service_name = "ai"
    env_var_name = "AI_PROVIDER_MODE"

    @abstractmethod
    async def generate_itinerary_suggestion(
        self,
        city_name: str,
        duration_days: int,
        budget_eur: float,
        travel_style: str,
        preferences: list[str],
    ) -> dict[str, Any]:
        """Génère une suggestion de programme de voyage adapté aux goûts et au budget."""

    @abstractmethod
    async def generate_structured_itinerary_raw(
        self,
        *,
        city_name: str,
        trip_dates: list[date],
        budget_eur: float,
        pace: str,
        tastes: list[str],
        available_places: list[dict[str, Any]],
        weather_by_date: dict[str, dict[str, Any]],
        attempt: int = 1,
        allow_outdoor_in_rain: bool = False,
    ) -> str | dict[str, Any]:
        """Retourne un JSON (str ou dict) d'itinéraire structuré validable par Pydantic."""

    @abstractmethod
    async def generate_chat_reply(
        self,
        *,
        user_message: str,
        safe_trip_context: dict[str, Any],
        chat_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Génère une réponse d'assistant de voyage basée exclusivement sur le contexte sécurisé du voyage."""


class BasePlacesProvider(BaseServiceProvider, ABC):
    service_name = "places"
    env_var_name = "PLACES_PROVIDER_MODE"

    @abstractmethod
    async def search_city_highlights(
        self,
        city_name: str,
        category: str | None = None,
        travel_style: str = "STANDARD",
    ) -> list[dict[str, Any]]:
        """Recherche les meilleurs lieux, hôtels et restaurants d'une ville."""


class BaseRoutingProvider(BaseServiceProvider, ABC):
    service_name = "routing"
    env_var_name = "ROUTING_PROVIDER_MODE"

    @abstractmethod
    async def compute_transit_leg(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        mode: str = "METRO",
    ) -> dict[str, Any]:
        """Calcule le temps de trajet et la distance entre deux coordonnées (réel ou estimé)."""
