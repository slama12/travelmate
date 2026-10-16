from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
import re
from typing import Any
import uuid

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
    CityNotSimulatedError,
)

REALISTIC_FLIGHTS_CATALOG: dict[str, dict[str, Any]] = {
    "HND": {
        "city": "Tokyo",
        "airlines": [("AF", "Air France"), ("NH", "All Nippon Airways"), ("JL", "Japan Airlines")],
        "base_price_eur": Decimal("780.00"),
        "duration_hours": 13,
    },
    "NRT": {
        "city": "Tokyo",
        "airlines": [("AF", "Air France"), ("JL", "Japan Airlines")],
        "base_price_eur": Decimal("740.00"),
        "duration_hours": 13,
    },
    "FCO": {
        "city": "Rome",
        "airlines": [("AF", "Air France"), ("AZ", "ITA Airways"), ("TO", "Transavia")],
        "base_price_eur": Decimal("145.00"),
        "duration_hours": 2,
    },
    "JFK": {
        "city": "New York",
        "airlines": [("AF", "Air France"), ("DL", "Delta Air Lines"), ("AA", "American Airlines")],
        "base_price_eur": Decimal("540.00"),
        "duration_hours": 8,
    },
    "RAK": {
        "city": "Marrakech",
        "airlines": [("AT", "Royal Air Maroc"), ("AF", "Air France"), ("TO", "Transavia")],
        "base_price_eur": Decimal("165.00"),
        "duration_hours": 3,
    },
    "CDG": {
        "city": "Paris",
        "airlines": [("AF", "Air France"), ("LH", "Lufthansa")],
        "base_price_eur": Decimal("130.00"),
        "duration_hours": 2,
    },
}

REALISTIC_CITY_PLACES: dict[str, list[dict[str, Any]]] = {
    "Paris": [
        {
            "name": "Musée du Louvre",
            "description": "Le plus grand musée d'art et d'antiquités au monde au cœur du Palais du Louvre.",
            "category": "CULTURE",
            "is_outdoor": False,
            "latitude": 48.8606,
            "longitude": 2.3376,
            "recommended_duration_min": 180,
            "estimated_cost": 22.0,
            "price_tier": "STANDARD",
            "avg_rating": 4.8,
            "opening_hours": {"daily": "09:00-18:00"},
            "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/6/66/Louvre_Museum_Wikimedia_Commons.jpg"],
            "source_provider": "simulated",
        },
        {
            "name": "Jardin du Luxembourg",
            "description": "Magnifique parc du Sénat avec bassins, statues et chaises vertes emblématiques.",
            "category": "NATURE",
            "is_outdoor": True,
            "latitude": 48.8462,
            "longitude": 2.3372,
            "recommended_duration_min": 90,
            "estimated_cost": 0.0,
            "price_tier": "ECONOMIC",
            "avg_rating": 4.9,
            "opening_hours": {"daily": "07:30-20:30"},
            "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/9/92/LuxembourgMontparnasse.JPG"],
            "source_provider": "simulated",
        },
        {
            "name": "Le Jules Verne (Tour Eiffel)",
            "description": "Restaurant gastronomique étoilé perché au 2e étage de la Tour Eiffel.",
            "category": "RESTAURANT",
            "is_outdoor": False,
            "latitude": 48.8584,
            "longitude": 2.2945,
            "recommended_duration_min": 150,
            "estimated_cost": 290.0,
            "price_tier": "LUXURY",
            "avg_rating": 4.7,
            "opening_hours": {"daily": "12:00-13:30, 19:00-21:00"},
            "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/b/b8/Le_Jules_Verne.jpg"],
            "source_provider": "simulated",
        },
        {
            "name": "Bouillon Chartier Grands Boulevards",
            "description": "Brasserie parisienne historique Belle Époque à petits prix.",
            "category": "RESTAURANT",
            "is_outdoor": False,
            "latitude": 48.8719,
            "longitude": 2.3431,
            "recommended_duration_min": 75,
            "estimated_cost": 24.0,
            "price_tier": "ECONOMIC",
            "avg_rating": 4.5,
            "opening_hours": {"daily": "11:30-00:00"},
            "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/1/14/Paris_Chartier_1304.jpg"],
            "source_provider": "simulated",
        },
    ],
    "Tokyo": [
        {
            "name": "Temple Senso-ji (Asakusa)",
            "description": "Le plus ancien temple bouddhiste de Tokyo et son allée commerçante Nakamise-dori.",
            "category": "CULTURE",
            "is_outdoor": True,
            "latitude": 35.7148,
            "longitude": 139.7967,
            "recommended_duration_min": 120,
            "estimated_cost": 0.0,
            "price_tier": "ECONOMIC",
            "avg_rating": 4.8,
            "opening_hours": {"daily": "06:00-17:00"},
            "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/4/43/Sensoji_2023.jpg"],
            "source_provider": "simulated",
        },
        {
            "name": "teamLab Planets Tokyo",
            "description": "Musée d'art numérique immersif où l'on marche pieds nus dans l'eau et la lumière.",
            "category": "CULTURE",
            "is_outdoor": False,
            "latitude": 35.6491,
            "longitude": 139.7898,
            "recommended_duration_min": 120,
            "estimated_cost": 32.0,
            "price_tier": "STANDARD",
            "avg_rating": 4.9,
            "opening_hours": {"daily": "09:00-22:00"},
            "hero_photos": ["https://images.unsplash.com/photo-1503899036084-c55cdd92da26?auto=format&fit=crop&w=1200&q=80"],
            "source_provider": "simulated",
        },
        {
            "name": "Jardin National Shinjuku Gyoen",
            "description": "Immense parc impérial mêlant jardins japonais traditionnels, anglais et français.",
            "category": "NATURE",
            "is_outdoor": True,
            "latitude": 35.6852,
            "longitude": 139.7101,
            "recommended_duration_min": 120,
            "estimated_cost": 4.0,
            "price_tier": "ECONOMIC",
            "avg_rating": 4.9,
            "opening_hours": {"daily": "09:00-16:30"},
            "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/9/9d/Shinjuku_Gyoen_National_Garden_-_sakura_3.JPG"],
            "source_provider": "simulated",
        },
        {
            "name": "Sukiyabashi Jiro Roppongi",
            "description": "Comptoir d'omakase sushi de haute tradition à Tokyo.",
            "category": "RESTAURANT",
            "is_outdoor": False,
            "latitude": 35.6604,
            "longitude": 139.7292,
            "recommended_duration_min": 90,
            "estimated_cost": 260.0,
            "price_tier": "LUXURY",
            "avg_rating": 4.9,
            "opening_hours": {"daily": "11:30-14:00, 17:30-21:00"},
            "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/9/92/Inside_Sukiyabashi_Jiro_%2811557082593%29.jpg"],
            "source_provider": "simulated",
        },
    ],
    "Rome": [
        {
            "name": "Colisée & Forum Romain",
            "description": "L'amphithéâtre flavien emblématique et le cœur politique de la Rome antique.",
            "category": "CULTURE",
            "is_outdoor": True,
            "latitude": 41.8902,
            "longitude": 12.4922,
            "recommended_duration_min": 180,
            "estimated_cost": 18.0,
            "price_tier": "STANDARD",
            "avg_rating": 4.9,
            "opening_hours": {"daily": "08:30-19:00"},
            "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/d/de/Colosseo_2020.jpg"],
            "source_provider": "simulated",
        },
        {
            "name": "Trattoria Da Enzo al 29",
            "description": "Trattoria romaine authentique au cœur du Trastevere (Carbonara & Cacio e Pepe).",
            "category": "RESTAURANT",
            "is_outdoor": False,
            "latitude": 41.8879,
            "longitude": 12.4777,
            "recommended_duration_min": 90,
            "estimated_cost": 28.0,
            "price_tier": "ECONOMIC",
            "avg_rating": 4.7,
            "opening_hours": {"daily": "12:15-15:00, 19:00-23:00"},
            "hero_photos": ["https://images.unsplash.com/photo-1551183053-bf91a1d81141?auto=format&fit=crop&w=1200&q=80"],
            "source_provider": "simulated",
        },
    ],
    "New York": [
        {
            "name": "Central Park",
            "description": "Poumon vert de 341 hectares au cœur de Manhattan.",
            "category": "NATURE",
            "is_outdoor": True,
            "latitude": 40.7812,
            "longitude": -73.9665,
            "recommended_duration_min": 150,
            "estimated_cost": 0.0,
            "price_tier": "ECONOMIC",
            "avg_rating": 4.9,
            "opening_hours": {"daily": "06:00-01:00"},
            "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/0/05/Southwest_corner_of_Central_Park%2C_looking_east%2C_NYC.jpg"],
            "source_provider": "simulated",
        },
        {
            "name": "Katz's Delicatessen",
            "description": "Institution new-yorkaise du Lower East Side célèbre pour son pastrami depuis 1888.",
            "category": "RESTAURANT",
            "is_outdoor": False,
            "latitude": 40.7222,
            "longitude": -73.9874,
            "recommended_duration_min": 75,
            "estimated_cost": 32.0,
            "price_tier": "STANDARD",
            "avg_rating": 4.7,
            "opening_hours": {"daily": "08:00-23:00"},
            "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/b/b2/Katz%27s_Delicatessen_%2851623899326%29.jpg"],
            "source_provider": "simulated",
        },
    ],
    "Marrakech": [
        {
            "name": "Jardin Majorelle & Musée Yves Saint Laurent",
            "description": "Oasis botanique au bleu cobalt iconique créée par Jacques Majorelle.",
            "category": "NATURE",
            "is_outdoor": True,
            "latitude": 31.6415,
            "longitude": -8.0033,
            "recommended_duration_min": 120,
            "estimated_cost": 28.0,
            "price_tier": "STANDARD",
            "avg_rating": 4.8,
            "opening_hours": {"daily": "08:00-18:30"},
            "hero_photos": ["https://upload.wikimedia.org/wikipedia/commons/5/57/Le_jardin_des_majorelle_16.JPG"],
            "source_provider": "simulated",
        },
        {
            "name": "La Grande Table Marocaine (Royal Mansour)",
            "description": "Haute gastronomie marocaine dans un palais de la Médina.",
            "category": "RESTAURANT",
            "is_outdoor": False,
            "latitude": 31.6258,
            "longitude": -7.9985,
            "recommended_duration_min": 150,
            "estimated_cost": 195.0,
            "price_tier": "LUXURY",
            "avg_rating": 4.9,
            "opening_hours": {"daily": "19:00-23:00"},
            "hero_photos": ["https://images.unsplash.com/photo-1541518763669-27fef04b14ea?auto=format&fit=crop&w=1200&q=80"],
            "source_provider": "simulated",
        },
    ],
}


class SimulatedGmailProvider(BaseGmailProvider):
    mode = "simulated"

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
        message_id = f"sim-gmail-{uuid.uuid4().hex[:12]}"
        return {
            "provider": "SimulatedGmailProvider",
            "mode": self.mode,
            "sent": True,
            "message_id": message_id,
            "sender": self.settings.GMAIL_SENDER_EMAIL,
            "recipient": recipient_email,
            "subject": f"[TravelMate] Confirmation billet d'avion {origin_iata} -> {destination_iata} (PNR: {pnr})",
            "preview": (
                f"Bonjour {passenger_name}, votre vol {origin_iata} -> {destination_iata} "
                f"(départ {departure_at.isoformat()}, retour {return_at.isoformat()}) "
                f"au tarif de {price_eur:.2f} EUR est confirmé."
            ),
        }


class SimulatedCalendarProvider(BaseCalendarProvider):
    mode = "simulated"

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
        event_id = f"sim-gcal-{uuid.uuid4().hex[:10]}"
        return {
            "provider": "SimulatedCalendarProvider",
            "mode": self.mode,
            "action": "created",
            "calendar_id": calendar_id,
            "event_id": event_id,
            "title": title,
            "location": location_name,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "timezone": timezone_name,
            "html_link": f"https://calendar.google.com/calendar/event?eid={event_id}",
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
        return {
            "provider": "SimulatedCalendarProvider",
            "mode": self.mode,
            "action": "updated",
            "calendar_id": calendar_id,
            "event_id": event_id,
            "title": title,
            "location": location_name,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "timezone": timezone_name,
            "html_link": f"https://calendar.google.com/calendar/event?eid={event_id}",
        }

    async def delete_visit_event(
        self,
        calendar_id: str,
        event_id: str,
    ) -> dict[str, Any]:
        return {
            "provider": "SimulatedCalendarProvider",
            "mode": self.mode,
            "action": "deleted",
            "calendar_id": calendar_id,
            "event_id": event_id,
            "deleted": True,
        }


class SimulatedFlightsProvider(BaseFlightsProvider):
    mode = "simulated"

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

        dest_key = destination_iata.upper()
        meta = REALISTIC_FLIGHTS_CATALOG.get(
            dest_key,
            {
                "city": dest_key,
                "airlines": [("AF", "Air France"), ("BA", "British Airways")],
                "base_price_eur": Decimal("320.00"),
                "duration_hours": 4,
            },
        )
        multiplier = {
            "ECONOMIC": Decimal("0.78"),
            "STANDARD": Decimal("1.00"),
            "LUXURY": Decimal("2.85"),
        }.get(travel_style.upper(), Decimal("1.00"))
        cabin = {"ECONOMIC": "ECONOMY", "STANDARD": "ECONOMY", "LUXURY": "BUSINESS"}.get(
            travel_style.upper(), "ECONOMY"
        )

        offers: list[dict[str, Any]] = []
        for idx, (code, airline_name) in enumerate(meta["airlines"]):
            dep_out = datetime.combine(departure_date, time(hour=8 + idx * 3, minute=30))
            arr_out = dep_out + timedelta(hours=meta["duration_hours"])
            dep_in = datetime.combine(return_date, time(hour=14 + idx * 2, minute=15))
            arr_in = dep_in + timedelta(hours=meta["duration_hours"])
            step_factor = Decimal(str(1 + idx * 0.08))
            price_dec = (meta["base_price_eur"] * multiplier * step_factor).quantize(Decimal("0.01"))
            offers.append(
                {
                    "offer_id": f"sim-flt-{origin_iata.upper()}-{dest_key}-{idx + 1}",
                    "airline_code": code,
                    "airline_name": airline_name,
                    "flight_number_outbound": f"{code}{104 + idx * 12}",
                    "flight_number_inbound": f"{code}{105 + idx * 12}",
                    "origin_iata": origin_iata.upper(),
                    "destination_iata": dest_key,
                    "destination_city": meta["city"],
                    "departure_outbound_at": dep_out.isoformat(),
                    "arrival_outbound_at": arr_out.isoformat(),
                    "departure_inbound_at": dep_in.isoformat(),
                    "arrival_inbound_at": arr_in.isoformat(),
                    "cabin_class": cabin,
                    "price_amount": str(price_dec),
                    "price_eur": float(price_dec),
                    "currency": "EUR",
                    "mode": self.mode,
                }
            )
        return offers


class SimulatedWeatherProvider(BaseWeatherProvider):
    mode = "simulated"

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
        patterns = [
            ("RAIN", "Pluie modérée (Alerte visites extérieures)", 80, 16.5),
            ("SUNNY", "Ensoleillé", 10, 23.0),
            ("STORM", "Orage prévu en après-midi", 85, 16.0),
            ("SUNNY", "Grand soleil", 5, 24.0),
            ("PARTLY_CLOUDY", "Partiellement nuageux", 20, 21.5),
        ]
        forecasts: list[dict[str, Any]] = []
        for idx in range(days):
            cond_code, summary, rain_prob, temp_c = patterns[idx % len(patterns)]
            forecasts.append(
                {
                    "city": city_name,
                    "date": (start_date + timedelta(days=idx)).isoformat(),
                    "condition_code": cond_code,
                    "summary": summary,
                    "precipitation_probability": rain_prob,
                    "is_rainy": rain_prob >= 60 or cond_code in {"RAIN", "STORM", "THUNDERSTORM"},
                    "temperature_celsius": temp_c,
                    "available": True,
                    "mode": self.mode,
                }
            )
        return forecasts


class SimulatedAIProvider(BaseAIProvider):
    mode = "simulated"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

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
        canonical_map = {k.lower(): k for k in REALISTIC_CITY_PLACES}
        matched_key = canonical_map.get(city_name.strip().lower())
        if not matched_key:
            raise CityNotSimulatedError(city_name)
        places = REALISTIC_CITY_PLACES[matched_key]
        return {
            "provider": "SimulatedAIProvider",
            "mode": self.mode,
            "model": self.settings.AI_MODEL_NAME,
            "city": matched_key,
            "duration_days": duration_days,
            "travel_style": travel_style,
            "preferences": preferences,
            "recommended_places": [p["name"] for p in places],
            "summary": (
                f"Programme optimisé sur {duration_days} jour(s) à {matched_key} "
                f"en mode {travel_style} (budget cible: {budget_eur:.0f} EUR)."
            ),
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
    ) -> str:
        """
        Génère de manière déterministe et réaliste un JSON d'itinéraire tenant compte :
        - des lieux réellement présents en base (available_places), sans aucun doublon de lieu,
        - des goûts (CULTURE, NATURE, FOOD/RESTAURANT, NIGHTLIFE),
        - du rythme (RELAX=1/j, NORMAL=2/j, INTENSE=3/j),
        - de la météo (aucun lieu en plein air un jour de pluie ou d'orage sauf demande explicite),
        - du regroupement géographique au plus proche voisin.
        """
        normalized_pace = (pace or "NORMAL").strip().upper()
        visits_per_day = {"RELAX": 1, "NORMAL": 2, "INTENSE": 3}.get(normalized_pace, 2)

        taste_to_categories: dict[str, set[str]] = {
            "CULTURE": {"CULTURE"},
            "NATURE": {"NATURE"},
            "FOOD": {"RESTAURANT"},
            "GASTRONOMIE": {"RESTAURANT"},
            "RESTAURANT": {"RESTAURANT"},
            "NUIT": {"NIGHTLIFE", "RESTAURANT"},
            "NIGHTLIFE": {"NIGHTLIFE", "RESTAURANT"},
            "SORTIES": {"NIGHTLIFE", "RESTAURANT"},
        }
        desired_categories: set[str] = set()
        for t in tastes or []:
            desired_categories.update(taste_to_categories.get(t.strip().upper(), {t.strip().upper()}))
        if not desired_categories:
            desired_categories = {"CULTURE", "NATURE", "RESTAURANT"}

        # Filtrage et tri déterministes par adéquation aux goûts et au budget
        def _place_priority(p: dict[str, Any]) -> tuple[int, int, float, str]:
            cat_match = 0 if str(p.get("category", "")).upper() in desired_categories else 1
            cost = float(p.get("estimated_cost", 0.0) or 0.0)
            budget_penalty = 1 if (budget_eur < 600 and cost > 120) else 0
            rating = -float(p.get("avg_rating", 4.5) or 4.5)
            return (cat_match, budget_penalty, rating, str(p.get("name", "")))

        ordered_places = sorted(available_places, key=_place_priority)
        indoor_queue = [p for p in ordered_places if not bool(p.get("is_outdoor", False))]
        outdoor_queue = [p for p in ordered_places if bool(p.get("is_outdoor", False))]
        used_place_ids: set[str] = set()

        slots: list[dict[str, Any]] = []
        target_dates = trip_dates[: max(1, min(len(trip_dates), 5))]
        default_times = ["10:00", "14:30", "19:30"]

        for day_idx, current_date in enumerate(target_dates):
            date_iso = current_date.isoformat()
            day_weather = weather_by_date.get(date_iso, {})
            cond_code = str(day_weather.get("condition_code", "")).upper()
            is_rainy_day = (
                bool(day_weather.get("is_rainy", False))
                or cond_code in {"RAIN", "STORM", "THUNDERSTORM"}
            )

            # Choix des candidats du jour selon la météo :
            # - Jour de pluie ou d'orage : jamais de lieu en plein air (sauf allow_outdoor_in_rain=True)
            # - Jour sec : priorité aux lieux en plein air puis lieux en intérieur
            # - Jamais de doublon de lieu sur l'ensemble du séjour
            day_places: list[dict[str, Any]] = []
            if is_rainy_day and not allow_outdoor_in_rain:
                candidate_pools: tuple[list[dict[str, Any]], ...] = (indoor_queue,)
            elif is_rainy_day and allow_outdoor_in_rain:
                candidate_pools = (indoor_queue, outdoor_queue)
            else:
                candidate_pools = (outdoor_queue, indoor_queue)

            for pool in candidate_pools:
                for candidate in pool:
                    pid = str(candidate["id"])
                    if pid not in used_place_ids and len(day_places) < visits_per_day:
                        day_places.append(candidate)
                        used_place_ids.add(pid)

            # Ordre au plus proche voisin pour minimiser les trajets du jour
            if len(day_places) > 1:
                nn_ordered = [day_places[0]]
                remaining = day_places[1:]
                while remaining:
                    last_p = nn_ordered[-1]
                    next_p = min(
                        remaining,
                        key=lambda cand: haversine_distance_km(
                            float(last_p.get("latitude", 0.0)),
                            float(last_p.get("longitude", 0.0)),
                            float(cand.get("latitude", 0.0)),
                            float(cand.get("longitude", 0.0)),
                        ),
                    )
                    nn_ordered.append(next_p)
                    remaining.remove(next_p)
                day_places = nn_ordered

            for slot_idx, p in enumerate(day_places):
                cat = str(p.get("category", "")).upper()
                if cat == "RESTAURANT":
                    start_hm = "12:30" if slot_idx == 0 and day_idx > 0 else "18:00"
                elif day_idx == 0 and slot_idx == 0:
                    start_hm = "14:00"
                else:
                    start_hm = default_times[min(slot_idx, len(default_times) - 1)]

                weather_note = (
                    "Lieu en intérieur privilégié en raison de la pluie ou de l'orage prévu"
                    if is_rainy_day and not p.get("is_outdoor", False)
                    else "Créneau optimisé par proximité géographique"
                )
                slots.append(
                    {
                        "place_id": str(p["id"]),
                        "place_name": str(p["name"]),
                        "visit_date": date_iso,
                        "local_start_time": start_hm,
                        "duration_minutes": int(p.get("recommended_duration_min", 90) or 90),
                        "transit_mode": "METRO",
                        "rationale_fr": weather_note,
                    }
                )

        payload = {
            "summary_fr": (
                f"Programme sur mesure à {city_name} au rythme {normalized_pace.lower()} "
                f"(budget {budget_eur:.0f} €), adapté à la météo et optimisé par quartier."
            ),
            "pace": normalized_pace,
            "slots": slots,
        }
        return json.dumps(payload, ensure_ascii=False)

    async def generate_chat_reply(
        self,
        *,
        user_message: str,
        safe_trip_context: dict[str, Any],
        chat_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Assistant de voyage déterministe et sécurisé :
        - Exploite le programme, le vol, l'hébergement, le budget et la météo du voyage en cours.
        - Détecte les demandes d'ajout, déplacement ou suppression de visite et construit une
          proposition d'action qui devra être validée par le moteur ET confirmée par l'utilisateur.
        """
        msg_lower = user_message.lower().strip()
        trip_info = safe_trip_context.get("trip", {})
        city_name = trip_info.get("city_name", "votre destination")
        itinerary_items: list[dict[str, Any]] = safe_trip_context.get("itinerary", [])
        available_places: list[dict[str, Any]] = safe_trip_context.get("available_places", [])
        flight_info = safe_trip_context.get("flight")
        acc_info = safe_trip_context.get("accommodation")
        budget_info = safe_trip_context.get("budget", {})
        weather_list: list[dict[str, Any]] = safe_trip_context.get("weather", [])

        # Extraction éventuelle d'une date (YYYY-MM-DD) et d'une heure (HH:MM ou HhMM)
        date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", user_message)
        time_match = re.search(r"\b(\d{1,2})\s*(?:h|:)\s*(\d{2})?\b", msg_lower)
        extracted_time: str | None = None
        if time_match:
            hh = int(time_match.group(1))
            mm = int(time_match.group(2) or "0")
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                extracted_time = f"{hh:02d}:{mm:02d}"

        default_date_str = (
            date_match.group(1)
            if date_match
            else (
                itinerary_items[0]["visit_date"]
                if itinerary_items
                else (weather_list[0]["date"] if weather_list else date.today().isoformat())
            )
        )

        # Recherche d'un lieu mentionné dans le message
        def _find_scheduled_item() -> dict[str, Any] | None:
            for item in itinerary_items:
                p_name = str(item.get("place_name", "")).lower()
                tokens = [tok for tok in re.split(r"\W+", p_name) if len(tok) >= 4]
                if p_name and (p_name in msg_lower or any(t in msg_lower for t in tokens)):
                    return item
            return itinerary_items[0] if itinerary_items else None

        def _find_place_in_catalog() -> dict[str, Any] | None:
            for p in available_places:
                p_name = str(p.get("name", "")).lower()
                tokens = [tok for tok in re.split(r"\W+", p_name) if len(tok) >= 4]
                if p_name and (p_name in msg_lower or any(t in msg_lower for t in tokens)):
                    return p
            scheduled_ids = {i.get("place_id") for i in itinerary_items}
            for p in available_places:
                if p.get("id") not in scheduled_ids:
                    return p
            return available_places[0] if available_places else None

        # 1. Intention : Supprimer / retirer une visite
        if any(kw in msg_lower for kw in ("retire", "retirer", "supprime", "supprimer", "enlève", "enlever", "annule")):
            target_item = _find_scheduled_item()
            if target_item:
                return {
                    "reply": (
                        f"Je peux retirer la visite « {target_item['place_name']} » prévue le "
                        f"{target_item['visit_date']} à {target_item['local_start_time']}. "
                        "Confirmez-vous cette suppression ?"
                    ),
                    "proposed_action": {
                        "action_type": "REMOVE_VISIT",
                        "item_id": target_item["item_id"],
                        "place_id": target_item["place_id"],
                        "place_name": target_item["place_name"],
                        "visit_date": target_item["visit_date"],
                        "local_start_time": target_item["local_start_time"],
                        "duration_minutes": int(target_item.get("duration_minutes", 90)),
                        "transit_mode": target_item.get("transit_mode", "METRO"),
                    },
                }

        # 2. Intention : Déplacer / décaler une visite
        if any(kw in msg_lower for kw in ("déplace", "deplace", "déplacer", "deplacer", "décale", "decale", "change l'heure")):
            target_item = _find_scheduled_item()
            if target_item:
                new_date = date_match.group(1) if date_match else target_item["visit_date"]
                new_time = extracted_time or "15:00"
                return {
                    "reply": (
                        f"Je vous propose de déplacer « {target_item['place_name']} » au "
                        f"{new_date} à {new_time}. Souhaitez-vous appliquer ce changement ?"
                    ),
                    "proposed_action": {
                        "action_type": "MOVE_VISIT",
                        "item_id": target_item["item_id"],
                        "place_id": target_item["place_id"],
                        "place_name": target_item["place_name"],
                        "visit_date": new_date,
                        "local_start_time": new_time,
                        "duration_minutes": int(target_item.get("duration_minutes", 90)),
                        "transit_mode": target_item.get("transit_mode", "METRO"),
                    },
                }

        # 3. Intention : Ajouter / planifier une visite
        if any(kw in msg_lower for kw in ("ajoute", "ajouter", "planifie", "planifier", "insère", "insere", "visiter")):
            target_place = _find_place_in_catalog()
            if target_place:
                new_time = extracted_time or "14:00"
                return {
                    "reply": (
                        f"Je vous propose d'ajouter « {target_place['name']} » le "
                        f"{default_date_str} à {new_time} ({target_place['recommended_duration_min']} min). "
                        "Rien n'est modifié tant que vous ne confirmez pas."
                    ),
                    "proposed_action": {
                        "action_type": "ADD_VISIT",
                        "item_id": None,
                        "place_id": target_place["id"],
                        "place_name": target_place["name"],
                        "visit_date": default_date_str,
                        "local_start_time": new_time,
                        "duration_minutes": int(target_place.get("recommended_duration_min", 90)),
                        "transit_mode": "METRO",
                    },
                }

        # 4. Réponse informative contextualisée (vol, hébergement, budget, météo, programme)
        flight_summary = (
            f"Vol {flight_info['origin_iata']} → {flight_info['destination_iata']} "
            f"({flight_info['airline']}, référence {flight_info['pnr_reference']})"
            if flight_info
            else "aucun vol réservé pour l'instant"
        )
        acc_summary = (
            f"hébergement « {acc_info['name']} » ({acc_info['neighborhood']})"
            if acc_info
            else "hébergement restant à choisir"
        )
        budget_total = budget_info.get("planned_total", trip_info.get("total_budget_planned", 2000))
        weather_brief = (
            f"{weather_list[0]['summary']} ({weather_list[0]['temperature_celsius']}°C)"
            if weather_list and weather_list[0].get("available", True) and weather_list[0].get("temperature_celsius") is not None
            else "Prévision non disponible"
        )
        return {
            "reply": (
                f"Pour votre séjour à {city_name} : {flight_summary}, {acc_summary}, "
                f"budget prévu de {budget_total} {trip_info.get('currency', 'EUR')}, "
                f"météo du premier jour : {weather_brief}, et {len(itinerary_items)} visite(s) au programme. "
                "Vous pouvez me demander d'ajouter, déplacer ou retirer une visite."
            ),
            "proposed_action": None,
        }


class SimulatedPlacesProvider(BasePlacesProvider):
    mode = "simulated"

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
        canonical_map = {k.lower(): k for k in REALISTIC_CITY_PLACES}
        matched_key = canonical_map.get(city_name.strip().lower())
        if not matched_key:
            raise CityNotSimulatedError(city_name)

        items = [dict(item) for item in REALISTIC_CITY_PLACES[matched_key]]
        if category:
            items = [i for i in items if i["category"].upper() == category.upper()]
        return items


class SimulatedRoutingProvider(BaseRoutingProvider):
    mode = "simulated"

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
            "provider": "SimulatedHaversine",
            "label_fr": "Temps estimé",
        }
