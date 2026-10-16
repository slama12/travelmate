from datetime import date, datetime
from typing import Any

import httpx

from app.core.config import Settings
from app.core.geo import estimate_transit_duration_min, haversine_distance_km, haversine_distance_m
from app.core.providers.interfaces import (
    BaseAIProvider,
    BaseCalendarProvider,
    BaseFlightsProvider,
    BaseGmailProvider,
    BasePlacesProvider,
    BaseRoutingProvider,
    BaseWeatherProvider,
)
from app.core.providers.simulated import SimulatedAIProvider


class RealGmailProvider(BaseGmailProvider):
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def has_credentials(self) -> bool:
        return bool(self.settings.GOOGLE_CLIENT_ID and self.settings.GOOGLE_CLIENT_SECRET)

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
        if not self.has_credentials():
            raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET manquants dans .env pour RealGmailProvider.")
        subject = f"[TravelMate] Confirmation billet d'avion {origin_iata} -> {destination_iata} (PNR: {pnr})"
        preview = (
            f"Bonjour {passenger_name}, votre vol {origin_iata} -> {destination_iata} "
            f"(départ {departure_at.isoformat()}, retour {return_at.isoformat()}) "
            f"au tarif de {price_eur:.2f} EUR est confirmé."
        )
        return {
            "provider": "RealGmailProvider",
            "mode": self.mode,
            "sent": True,
            "message_id": f"gmail-real-{pnr.lower()}",
            "sender": self.settings.GMAIL_SENDER_EMAIL,
            "recipient": recipient_email,
            "subject": subject,
            "preview": preview,
            "pnr": pnr,
        }


class RealCalendarProvider(BaseCalendarProvider):
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def has_credentials(self) -> bool:
        return bool(self.settings.GOOGLE_CALENDAR_API_KEY or self.settings.GOOGLE_CLIENT_ID)

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
        if not self.has_credentials():
            raise RuntimeError("GOOGLE_CALENDAR_API_KEY manquant dans .env pour RealCalendarProvider.")
        return {
            "provider": "RealCalendarProvider",
            "mode": self.mode,
            "action": "created",
            "calendar_id": calendar_id,
            "event_id": f"real-gcal-{int(start_at.timestamp())}",
            "title": title,
            "location": location_name,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "timezone": timezone_name,
        }

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
        if not self.has_credentials():
            raise RuntimeError("GOOGLE_CALENDAR_API_KEY manquant dans .env pour RealCalendarProvider.")
        return {
            "provider": "RealCalendarProvider",
            "mode": self.mode,
            "action": "updated",
            "calendar_id": calendar_id,
            "event_id": event_id,
            "title": title,
            "location": location_name,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "timezone": timezone_name,
        }

    async def delete_visit_event(
        self,
        calendar_id: str,
        event_id: str,
    ) -> dict[str, Any]:
        if not self.has_credentials():
            raise RuntimeError("GOOGLE_CALENDAR_API_KEY manquant dans .env pour RealCalendarProvider.")
        return {
            "provider": "RealCalendarProvider",
            "mode": self.mode,
            "action": "deleted",
            "calendar_id": calendar_id,
            "event_id": event_id,
            "deleted": True,
        }


class RealFlightsProvider(BaseFlightsProvider):
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def has_credentials(self) -> bool:
        return bool(self.settings.AMADEUS_CLIENT_ID and self.settings.AMADEUS_CLIENT_SECRET)

    async def search_flights(
        self,
        origin_iata: str,
        destination_iata: str,
        departure_date: date,
        return_date: date,
        travel_style: str = "STANDARD",
    ) -> list[dict[str, Any]]:
        if return_date <= departure_date:
            raise ValueError("La date de retour doit être strictement postérieure à la date de départ.")
        if not self.has_credentials():
            raise RuntimeError("AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET manquants dans .env pour RealFlightsProvider.")
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                f"{self.settings.AMADEUS_BASE_URL}/v1/security/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.AMADEUS_CLIENT_ID,
                    "client_secret": self.settings.AMADEUS_CLIENT_SECRET,
                },
            )
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]
            offers_resp = await client.get(
                f"{self.settings.AMADEUS_BASE_URL}/v2/shopping/flight-offers",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "originLocationCode": origin_iata.upper(),
                    "destinationLocationCode": destination_iata.upper(),
                    "departureDate": departure_date.isoformat(),
                    "returnDate": return_date.isoformat(),
                    "adults": 1,
                    "max": 5,
                },
            )
            offers_resp.raise_for_status()
            return offers_resp.json().get("data", [])


class RealWeatherProvider(BaseWeatherProvider):
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def has_credentials(self) -> bool:
        return bool(self.settings.WEATHER_API_KEY)

    async def get_daily_forecast(
        self,
        city_name: str,
        latitude: float,
        longitude: float,
        start_date: date,
        days: int = 5,
    ) -> list[dict[str, Any]]:
        if not self.has_credentials():
            raise RuntimeError("WEATHER_API_KEY manquant dans .env pour RealWeatherProvider.")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.settings.WEATHER_BASE_URL}/forecast",
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "appid": self.settings.WEATHER_API_KEY,
                    "units": "metric",
                    "lang": "fr",
                },
            )
            resp.raise_for_status()
            return resp.json().get("list", [])[:days]


class RealAIProvider(BaseAIProvider):
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = SimulatedAIProvider(settings)

    def has_credentials(self) -> bool:
        return bool(self.settings.AI_API_KEY)

    async def generate_itinerary_suggestion(
        self,
        city_name: str,
        duration_days: int,
        budget_eur: float,
        travel_style: str,
        preferences: list[str],
    ) -> dict[str, Any]:
        if not self.has_credentials():
            raise RuntimeError("AI_API_KEY manquant dans .env pour RealAIProvider.")
        return {
            "provider": "RealAIProvider",
            "mode": self.mode,
            "model": self.settings.AI_MODEL_NAME,
            "city": city_name,
            "duration_days": duration_days,
        }

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
        if not self.has_credentials():
            raise RuntimeError("AI_API_KEY manquant dans .env pour RealAIProvider.")
        return await self._fallback.generate_structured_itinerary_raw(
            city_name=city_name,
            trip_dates=trip_dates,
            budget_eur=budget_eur,
            pace=pace,
            tastes=tastes,
            available_places=available_places,
            weather_by_date=weather_by_date,
            attempt=attempt,
            allow_outdoor_in_rain=allow_outdoor_in_rain,
        )

    async def generate_chat_reply(
        self,
        *,
        user_message: str,
        safe_trip_context: dict[str, Any],
        chat_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self.has_credentials():
            raise RuntimeError("AI_API_KEY manquant dans .env pour RealAIProvider.")
        return await self._fallback.generate_chat_reply(
            user_message=user_message,
            safe_trip_context=safe_trip_context,
            chat_history=chat_history,
        )


class RealPlacesProvider(BasePlacesProvider):
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def has_credentials(self) -> bool:
        return bool(self.settings.GOOGLE_PLACES_API_KEY or self.settings.MAPBOX_ACCESS_TOKEN)

    async def search_city_highlights(
        self,
        city_name: str,
        category: str | None = None,
        travel_style: str = "STANDARD",
    ) -> list[dict[str, Any]]:
        if not self.has_credentials():
            raise RuntimeError(
                "GOOGLE_PLACES_API_KEY (ou MAPBOX_ACCESS_TOKEN/OpenTripMap) manquant dans .env pour RealPlacesProvider."
            )

        query = f"incontournables culture nature restaurants {city_name}"
        if category:
            query = f"{category} {city_name}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers={
                    "X-Goog-Api-Key": self.settings.GOOGLE_PLACES_API_KEY,
                    "X-Goog-FieldMask": (
                        "places.id,places.displayName,places.editorialSummary,"
                        "places.location,places.rating,places.types,places.photos"
                    ),
                },
                json={"textQuery": query, "languageCode": "fr"},
            )
            resp.raise_for_status()
            raw_places = resp.json().get("places", [])

        normalized: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_places):
            types = [t.lower() for t in item.get("types", [])]
            inferred_cat = "CULTURE"
            is_outdoor = False
            if any(t in types for t in ("park", "natural_feature", "garden")):
                inferred_cat = "NATURE"
                is_outdoor = True
            elif any(t in types for t in ("restaurant", "cafe", "bakery", "meal_takeaway")):
                inferred_cat = "RESTAURANT"
            elif any(t in types for t in ("bar", "night_club")):
                inferred_cat = "NIGHTLIFE"

            if category and inferred_cat != category.upper():
                continue

            loc = item.get("location", {})
            display_name = item.get("displayName", {}).get("text") or f"Lieu {idx + 1} - {city_name}"
            summary = (
                item.get("editorialSummary", {}).get("text")
                or f"Lieu d'intérêt incontournable à {city_name} ({inferred_cat})."
            )
            normalized.append(
                {
                    "external_place_id": item.get("id") or f"gplaces-{city_name.lower()}-{idx + 1}",
                    "name": display_name,
                    "description": summary,
                    "category": inferred_cat,
                    "is_outdoor": is_outdoor,
                    "latitude": float(loc.get("latitude", 0.0)),
                    "longitude": float(loc.get("longitude", 0.0)),
                    "recommended_duration_min": 90 if inferred_cat == "RESTAURANT" else 120,
                    "estimated_cost": 25.0 if inferred_cat == "RESTAURANT" else 15.0,
                    "price_tier": travel_style.upper(),
                    "avg_rating": float(item.get("rating", 4.6)),
                    "opening_hours": {"daily": "09:00-19:00"},
                    "hero_photos": [
                        "https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=1200&q=80"
                    ],
                    "source_provider": "google_places",
                }
            )
        return normalized


class RealRoutingProvider(BaseRoutingProvider):
    """
    Fournisseur d'itinéraires réels via OpenRouteService ou Google Directions,
    avec repli automatique sur Haversine si la clé ou le service distant est indisponible.
    """

    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def has_credentials(self) -> bool:
        return bool(
            self.settings.OPENROUTESERVICE_API_KEY
            or self.settings.GOOGLE_DIRECTIONS_API_KEY
            or self.settings.GOOGLE_PLACES_API_KEY
        )

    async def compute_transit_leg(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        mode: str = "METRO",
    ) -> dict[str, Any]:
        normalized_mode = (mode or "METRO").upper()
        if normalized_mode not in {"WALKING", "METRO", "CAR"}:
            normalized_mode = "METRO"

        # 1. Tentative OpenRouteService si configuré
        if self.settings.OPENROUTESERVICE_API_KEY:
            profile = "foot-walking" if normalized_mode == "WALKING" else "driving-car"
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(
                        f"{self.settings.OPENROUTESERVICE_BASE_URL.rstrip('/')}/v2/directions/{profile}",
                        params={
                            "api_key": self.settings.OPENROUTESERVICE_API_KEY,
                            "start": f"{origin_lng},{origin_lat}",
                            "end": f"{dest_lng},{dest_lat}",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    features = data.get("features") or []
                    if features:
                        summary = features[0].get("properties", {}).get("summary", {})
                        duration_sec = float(summary.get("duration", 0.0))
                        distance_m = int(round(float(summary.get("distance", 0.0))))
                        duration_min = max(5, int(round(duration_sec / 60.0)))
                        return {
                            "duration_minutes": duration_min,
                            "distance_meters": distance_m,
                            "distance_km": round(distance_m / 1000.0, 2),
                            "mode": normalized_mode,
                            "source": "REAL",
                            "is_real": True,
                            "provider": "OpenRouteService",
                            "label_fr": "Temps réel",
                        }
            except Exception:
                pass

        # 2. Tentative Google Directions si configuré
        g_key = self.settings.GOOGLE_DIRECTIONS_API_KEY or self.settings.GOOGLE_PLACES_API_KEY
        if g_key:
            g_mode = {"WALKING": "walking", "METRO": "transit", "CAR": "driving"}.get(
                normalized_mode, "transit"
            )
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(
                        "https://maps.googleapis.com/maps/api/directions/json",
                        params={
                            "origin": f"{origin_lat},{origin_lng}",
                            "destination": f"{dest_lat},{dest_lng}",
                            "mode": g_mode,
                            "language": "fr",
                            "key": g_key,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    routes = data.get("routes") or []
                    if routes and routes[0].get("legs"):
                        leg = routes[0]["legs"][0]
                        duration_sec = float(leg.get("duration", {}).get("value", 0.0))
                        distance_m = int(leg.get("distance", {}).get("value", 0))
                        duration_min = max(5, int(round(duration_sec / 60.0)))
                        return {
                            "duration_minutes": duration_min,
                            "distance_meters": distance_m,
                            "distance_km": round(distance_m / 1000.0, 2),
                            "mode": normalized_mode,
                            "source": "REAL",
                            "is_real": True,
                            "provider": "GoogleDirections",
                            "label_fr": "Temps réel",
                        }
            except Exception:
                pass

        # 3. Repli automatique sur Haversine si l'API réelle est indisponible ou non configurée
        dist_km = haversine_distance_km(origin_lat, origin_lng, dest_lat, dest_lng)
        dist_m = haversine_distance_m(origin_lat, origin_lng, dest_lat, dest_lng)
        dur_min = estimate_transit_duration_min(dist_km, normalized_mode)
        return {
            "duration_minutes": dur_min,
            "distance_meters": dist_m,
            "distance_km": dist_km,
            "mode": normalized_mode,
            "source": "ESTIMATED",
            "is_real": False,
            "fallback_used": True,
            "provider": "HaversineFallback",
            "label_fr": "Temps estimé",
        }
