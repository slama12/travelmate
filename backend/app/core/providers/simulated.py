from datetime import date, datetime, time, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
import json
import re
from typing import Any
import unicodedata
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
    BaseVoiceSTTProvider,
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

from app.core.seed import SEED_DESTINATIONS

REALISTIC_CITY_PLACES: dict[str, list[dict[str, Any]]] = {
    dest_entry["city_name"]: [
        {
            **place,
            "category": str(place["category"].value if hasattr(place["category"], "value") else place["category"]),
            "price_tier": str(place["price_tier"].value if hasattr(place["price_tier"], "value") else place["price_tier"]),
            "estimated_cost": float(place["estimated_cost"]),
            "source_provider": "simulated",
        }
        for place in dest_entry["places"]
    ]
    for dest_entry in SEED_DESTINATIONS
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


from app.core.airports import (
    AIRPORTS_BY_IATA,
    AirportRecord,
    build_flight_comparator_urls,
    get_city_comparator_code,
    resolve_airport_record,
)

DEMO_CITY_METRO_CODES: set[str] = {"PAR", "TYO", "ROM", "NYC", "RAK"}

# Liaisons directes réelles vérifiées vers/entre les 5 villes de démo
VERIFIED_DEMO_DIRECT_ROUTES: dict[tuple[str, str], dict[str, Any]] = {
    ("PAR", "TYO"): {
        "city": "Tokyo",
        "airlines": [("AF", "Air France"), ("NH", "All Nippon Airways"), ("JL", "Japan Airlines")],
        "base_price_eur": Decimal("780.00"),
        "duration_hours": 13,
    },
    ("TYO", "PAR"): {
        "city": "Paris",
        "airlines": [("AF", "Air France"), ("NH", "All Nippon Airways"), ("JL", "Japan Airlines")],
        "base_price_eur": Decimal("780.00"),
        "duration_hours": 13,
    },
    ("PAR", "ROM"): {
        "city": "Rome",
        "airlines": [("AF", "Air France"), ("AZ", "ITA Airways"), ("TO", "Transavia")],
        "base_price_eur": Decimal("145.00"),
        "duration_hours": 2,
    },
    ("ROM", "PAR"): {
        "city": "Paris",
        "airlines": [("AF", "Air France"), ("AZ", "ITA Airways"), ("TO", "Transavia")],
        "base_price_eur": Decimal("145.00"),
        "duration_hours": 2,
    },
    ("PAR", "NYC"): {
        "city": "New York",
        "airlines": [("AF", "Air France"), ("DL", "Delta Air Lines"), ("AA", "American Airlines")],
        "base_price_eur": Decimal("540.00"),
        "duration_hours": 8,
    },
    ("NYC", "PAR"): {
        "city": "Paris",
        "airlines": [("AF", "Air France"), ("DL", "Delta Air Lines"), ("AA", "American Airlines")],
        "base_price_eur": Decimal("540.00"),
        "duration_hours": 8,
    },
    ("PAR", "RAK"): {
        "city": "Marrakech",
        "airlines": [("AT", "Royal Air Maroc"), ("AF", "Air France"), ("TO", "Transavia")],
        "base_price_eur": Decimal("165.00"),
        "duration_hours": 3,
    },
    ("RAK", "PAR"): {
        "city": "Paris",
        "airlines": [("AT", "Royal Air Maroc"), ("AF", "Air France"), ("TO", "Transavia")],
        "base_price_eur": Decimal("165.00"),
        "duration_hours": 3,
    },
    ("LON", "PAR"): {
        "city": "Paris",
        "airlines": [("AF", "Air France"), ("BA", "British Airways")],
        "base_price_eur": Decimal("130.00"),
        "duration_hours": 2,
    },
    ("FRA", "PAR"): {
        "city": "Paris",
        "airlines": [("AF", "Air France"), ("LH", "Lufthansa")],
        "base_price_eur": Decimal("130.00"),
        "duration_hours": 2,
    },
    ("NYC", "TYO"): {
        "city": "Tokyo",
        "airlines": [("JL", "Japan Airlines"), ("NH", "All Nippon Airways")],
        "base_price_eur": Decimal("890.00"),
        "duration_hours": 14,
    },
    ("TYO", "NYC"): {
        "city": "New York",
        "airlines": [("JL", "Japan Airlines"), ("NH", "All Nippon Airways")],
        "base_price_eur": Decimal("890.00"),
        "duration_hours": 14,
    },
    ("ROM", "NYC"): {
        "city": "New York",
        "airlines": [("AZ", "ITA Airways"), ("DL", "Delta Air Lines")],
        "base_price_eur": Decimal("580.00"),
        "duration_hours": 9,
    },
    ("NYC", "ROM"): {
        "city": "Rome",
        "airlines": [("AZ", "ITA Airways"), ("DL", "Delta Air Lines")],
        "base_price_eur": Decimal("580.00"),
        "duration_hours": 9,
    },
    ("ROM", "TYO"): {
        "city": "Tokyo",
        "airlines": [("AZ", "ITA Airways")],
        "base_price_eur": Decimal("820.00"),
        "duration_hours": 13,
    },
    ("TYO", "ROM"): {
        "city": "Rome",
        "airlines": [("AZ", "ITA Airways")],
        "base_price_eur": Decimal("820.00"),
        "duration_hours": 13,
    },
    ("ROM", "RAK"): {
        "city": "Marrakech",
        "airlines": [("AT", "Royal Air Maroc")],
        "base_price_eur": Decimal("185.00"),
        "duration_hours": 3,
    },
    ("RAK", "ROM"): {
        "city": "Rome",
        "airlines": [("AT", "Royal Air Maroc")],
        "base_price_eur": Decimal("185.00"),
        "duration_hours": 3,
    },
}

INTERCONTINENTAL_HUB_IATAS: tuple[str, ...] = (
    "SIN",
    "DXB",
    "DOH",
    "IST",
    "FRA",
    "AMS",
    "LHR",
    "MAD",
    "JFK",
    "ATL",
)


def _select_stopover_hubs(orig: AirportRecord, dest: AirportRecord) -> list[AirportRecord]:
    """Sélectionne les hubs d'escale OurAirports les plus cohérents géographiquement."""
    candidates: list[tuple[float, AirportRecord]] = []
    orig_metro = get_city_comparator_code(orig.iata_code, orig.municipality)
    dest_metro = get_city_comparator_code(dest.iata_code, dest.municipality)
    direct_km = haversine_distance_km(orig.latitude, orig.longitude, dest.latitude, dest.longitude)
    min_leg_km = max(600.0, direct_km * 0.20)
    for hub_iata in INTERCONTINENTAL_HUB_IATAS:
        hub = AIRPORTS_BY_IATA.get(hub_iata)
        if hub is None:
            continue
        hub_metro = get_city_comparator_code(hub.iata_code, hub.municipality)
        if hub_metro in {orig_metro, dest_metro}:
            continue
        leg1 = haversine_distance_km(orig.latitude, orig.longitude, hub.latitude, hub.longitude)
        leg2 = haversine_distance_km(hub.latitude, hub.longitude, dest.latitude, dest.longitude)
        if leg1 < min_leg_km or leg2 < min_leg_km:
            continue
        score = (leg1 + leg2) + 0.25 * abs(leg1 - leg2)
        candidates.append((score, hub))
    candidates.sort(key=lambda item: item[0])
    if candidates:
        return [item[1] for item in candidates[:2]]
    fallback = AIRPORTS_BY_IATA.get("DXB") or orig
    return [fallback]


def build_distance_based_example_offers(
    origin_iata: str,
    destination_iata: str,
    departure_date: date,
    return_date: date,
    travel_style: str = "STANDARD",
    mode: str = "simulated",
) -> list[dict[str, Any]]:
    """Génère des offres d'exemple calculées sur la distance OurAirports :
    - durée cohérente avec la distance,
    - escale par un hub réel si la distance est grande (> 4500 km),
    - prix indicatif selon le style Éco / Standard / Luxe,
    - sans nom de compagnie ni numéro de vol inventés."""
    orig_rec = resolve_airport_record(origin_iata) or AIRPORTS_BY_IATA["CDG"]
    dest_rec = resolve_airport_record(destination_iata)
    if dest_rec is None:
        return []

    orig_code = origin_iata.strip().upper()
    dest_code = destination_iata.strip().upper()
    orig_city_code = get_city_comparator_code(orig_code, orig_rec.municipality)
    dest_city_code = get_city_comparator_code(dest_code, dest_rec.municipality)
    comparator_urls = build_flight_comparator_urls(
        orig_code,
        dest_code,
        departure_date.isoformat(),
        return_date.isoformat(),
        origin_city=orig_rec.municipality,
        destination_city=dest_rec.municipality,
    )

    distance_km = round(
        haversine_distance_km(
            orig_rec.latitude,
            orig_rec.longitude,
            dest_rec.latitude,
            dest_rec.longitude,
        ),
        1,
    )

    style_key = (travel_style or "STANDARD").strip().upper()
    multiplier = {
        "ECONOMIC": Decimal("0.78"),
        "STANDARD": Decimal("1.00"),
        "LUXURY": Decimal("2.65"),
    }.get(style_key, Decimal("1.00"))
    cabin = {"ECONOMIC": "ECONOMY", "STANDARD": "ECONOMY", "LUXURY": "BUSINESS"}.get(
        style_key, "ECONOMY"
    )

    # Calcul du tarif de base aller-retour selon la distance orthodromique
    if distance_km <= 1000.0:
        base_price = Decimal(str(round(75.0 + distance_km * 0.14, 2)))
    elif distance_km <= 4500.0:
        base_price = Decimal(str(round(110.0 + distance_km * 0.11, 2)))
    else:
        base_price = Decimal(str(round(320.0 + distance_km * 0.068, 2)))

    needs_stopover = distance_km > 4500.0
    hubs = _select_stopover_hubs(orig_rec, dest_rec) if needs_stopover else []

    offers: list[dict[str, Any]] = []
    slot_hours = ((8, 30, 14, 15), (12, 15, 17, 45), (17, 40, 20, 10))
    for idx in range(3):
        dep_h, dep_m, ret_h, ret_m = slot_hours[idx]
        if needs_stopover:
            hub = hubs[idx % len(hubs)]
            routed_km = haversine_distance_km(
                orig_rec.latitude, orig_rec.longitude, hub.latitude, hub.longitude
            ) + haversine_distance_km(
                hub.latitude, hub.longitude, dest_rec.latitude, dest_rec.longitude
            )
            layover_min = 115 + idx * 20
            duration_min = max(360, int(round((routed_km / 830.0) * 60.0 + 40.0 + layover_min)))
            stops = 1
            hub_iata: str | None = hub.iata_code
            hub_city: str | None = hub.municipality
            stopover_label = f"1 escale à {hub.municipality} ({hub.iata_code})"
            outbound_ref = f"Aller • 1 escale ({hub.iata_code})"
            inbound_ref = f"Retour • 1 escale ({hub.iata_code})"
        else:
            cruise_kmh = 580.0 if distance_km <= 800.0 else 730.0
            duration_min = max(65, int(round((distance_km / cruise_kmh) * 60.0 + 35.0 + idx * 5)))
            stops = 0
            hub_iata = None
            hub_city = None
            stopover_label = "Direct"
            outbound_ref = "Aller direct"
            inbound_ref = "Retour direct"

        dep_out = datetime.combine(departure_date, time(hour=dep_h, minute=dep_m))
        arr_out = dep_out + timedelta(minutes=duration_min)
        dep_in = datetime.combine(return_date, time(hour=ret_h, minute=ret_m))
        if dep_in <= arr_out:
            dep_in = arr_out + timedelta(hours=4)
        arr_in = dep_in + timedelta(minutes=duration_min)

        step_factor = Decimal(str(1 + idx * 0.07))
        price_dec = (base_price * multiplier * step_factor).quantize(Decimal("0.01"))

        offers.append(
            {
                "offer_id": f"ex-flt-{orig_code}-{dest_code}-{idx + 1}",
                "airline_code": "",
                "airline_name": "Offre d'exemple",
                "flight_number_outbound": outbound_ref,
                "flight_number_inbound": inbound_ref,
                "origin_iata": orig_code,
                "destination_iata": dest_code,
                "origin_city_code": orig_city_code,
                "destination_city_code": dest_city_code,
                "destination_city": dest_rec.municipality,
                "departure_outbound_at": dep_out.isoformat(),
                "arrival_outbound_at": arr_out.isoformat(),
                "departure_inbound_at": dep_in.isoformat(),
                "arrival_inbound_at": arr_in.isoformat(),
                "cabin_class": cabin,
                "price_amount": str(price_dec),
                "price_eur": float(price_dec),
                "currency": "EUR",
                "mode": mode,
                "is_example_offer": True,
                "offer_badge": "Offre d'exemple",
                "price_label": "Prix indicatif",
                "banner_text": "Offres d'exemple, prix indicatifs",
                "distance_km": distance_km,
                "duration_outbound_minutes": duration_min,
                "duration_inbound_minutes": duration_min,
                "stops": stops,
                "stopover_hub_iata": hub_iata,
                "stopover_hub_city": hub_city,
                "stopover_label": stopover_label,
                "comparator_urls": comparator_urls,
            }
        )
    return offers


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

        orig_key = origin_iata.strip().upper()
        dest_key = destination_iata.strip().upper()
        orig_metro = get_city_comparator_code(orig_key)
        dest_metro = get_city_comparator_code(dest_key)

        # Pour les 5 villes de démo : compagnies réelles uniquement sur les liaisons qui existent
        meta = (
            VERIFIED_DEMO_DIRECT_ROUTES.get((orig_metro, dest_metro))
            if dest_metro in DEMO_CITY_METRO_CODES
            else None
        )
        if meta is None:
            return build_distance_based_example_offers(
                origin_iata=orig_key,
                destination_iata=dest_key,
                departure_date=departure_date,
                return_date=return_date,
                travel_style=travel_style,
                mode=self.mode,
            )

        orig_rec = resolve_airport_record(orig_key)
        dest_rec = resolve_airport_record(dest_key)
        distance_km = (
            round(
                haversine_distance_km(
                    orig_rec.latitude,
                    orig_rec.longitude,
                    dest_rec.latitude,
                    dest_rec.longitude,
                ),
                1,
            )
            if orig_rec and dest_rec
            else None
        )
        comparator_urls = build_flight_comparator_urls(
            orig_key,
            dest_key,
            departure_date.isoformat(),
            return_date.isoformat(),
            origin_city=orig_rec.municipality if orig_rec else None,
            destination_city=meta["city"],
        )

        multiplier = {
            "ECONOMIC": Decimal("0.78"),
            "STANDARD": Decimal("1.00"),
            "LUXURY": Decimal("2.85"),
        }.get(travel_style.upper(), Decimal("1.00"))
        cabin = {"ECONOMIC": "ECONOMY", "STANDARD": "ECONOMY", "LUXURY": "BUSINESS"}.get(
            travel_style.upper(), "ECONOMY"
        )
        duration_min = int(meta["duration_hours"]) * 60

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
                    "offer_id": f"sim-flt-{orig_key}-{dest_key}-{idx + 1}",
                    "airline_code": code,
                    "airline_name": airline_name,
                    "flight_number_outbound": f"{code}{104 + idx * 12}",
                    "flight_number_inbound": f"{code}{105 + idx * 12}",
                    "origin_iata": orig_key,
                    "destination_iata": dest_key,
                    "origin_city_code": orig_metro,
                    "destination_city_code": dest_metro,
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
                    "is_example_offer": False,
                    "offer_badge": "Offre d'exemple",
                    "price_label": "Prix indicatif",
                    "banner_text": "Offres d'exemple, prix indicatifs",
                    "distance_km": distance_km,
                    "duration_outbound_minutes": duration_min,
                    "duration_inbound_minutes": duration_min,
                    "stops": 0,
                    "stopover_hub_iata": None,
                    "stopover_hub_city": None,
                    "stopover_label": "Direct",
                    "comparator_urls": comparator_urls,
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

        def _is_evening_only(cand: dict[str, Any]) -> int:
            c_cat = str(cand.get("category", "")).upper()
            c_oh = str(cand.get("opening_hours", ""))
            if c_cat == "NIGHTLIFE":
                return 2
            if ("18:" in c_oh or "19:" in c_oh) and "12:" not in c_oh and "09:" not in c_oh and "10:" not in c_oh:
                return 1
            return 0

        ordered_places = sorted(available_places, key=_place_priority)
        indoor_queue = [p for p in ordered_places if not bool(p.get("is_outdoor", False))]
        outdoor_queue = [p for p in ordered_places if bool(p.get("is_outdoor", False))]
        used_place_ids: set[str] = set()

        slots: list[dict[str, Any]] = []
        target_dates = trip_dates[: max(1, min(len(trip_dates), 14))]
        default_times = ["10:00", "14:30", "17:30"]
        total_days = len(target_dates)

        reserved_last_day_id: str | None = None
        if total_days >= 6:
            daytime_indoors = [p for p in indoor_queue if _is_evening_only(p) == 0]
            if daytime_indoors:
                reserved_last_day_id = str(daytime_indoors[-1]["id"])

        for day_idx, current_date in enumerate(target_dates):
            date_iso = current_date.isoformat()
            day_weather = weather_by_date.get(date_iso, {})
            cond_code = str(day_weather.get("condition_code", "")).upper()
            is_rainy_day = (
                bool(day_weather.get("is_rainy", False))
                or cond_code in {"RAIN", "STORM", "THUNDERSTORM"}
            )
            is_final_day = total_days >= 6 and day_idx == total_days - 1

            # Répartition équilibrée sur tous les jours du séjour (y compris séjour de 8 jours)
            if total_days >= 7 and visits_per_day == 2 and day_idx >= total_days - 2:
                day_target_count = 1
            elif total_days > 5 and day_idx == total_days - 1:
                day_target_count = 1
            else:
                day_target_count = visits_per_day

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
                    if not is_final_day and pid == reserved_last_day_id:
                        continue
                    if is_final_day and _is_evening_only(candidate) > 0:
                        continue
                    if pid not in used_place_ids and len(day_places) < day_target_count:
                        day_places.append(candidate)
                        used_place_ids.add(pid)

            # Ordre au plus proche voisin tout en plaçant les visites de journée avant les lieux du soir
            if len(day_places) > 1:
                day_places.sort(key=_is_evening_only)
                nn_ordered = [day_places[0]]
                remaining = day_places[1:]
                while remaining:
                    last_p = nn_ordered[-1]
                    next_p = min(
                        remaining,
                        key=lambda cand: (
                            _is_evening_only(cand),
                            haversine_distance_km(
                                float(last_p.get("latitude", 0.0)),
                                float(last_p.get("longitude", 0.0)),
                                float(cand.get("latitude", 0.0)),
                                float(cand.get("longitude", 0.0)),
                            ),
                        ),
                    )
                    nn_ordered.append(next_p)
                    remaining.remove(next_p)
                day_places = nn_ordered

            for slot_idx, p in enumerate(day_places):
                cat = str(p.get("category", "")).upper()
                oh_str = str(p.get("opening_hours", ""))
                is_last_day_long_trip = total_days > 5 and day_idx == total_days - 1

                if is_last_day_long_trip:
                    start_hm = "09:30"
                elif cat == "NIGHTLIFE":
                    start_hm = "19:30"
                elif cat == "RESTAURANT":
                    if "19:00" in oh_str and "12:" not in oh_str:
                        start_hm = "18:00"
                    elif "19:30" in oh_str and "12:" not in oh_str:
                        start_hm = "19:30"
                    elif "18:30" in oh_str and "12:" not in oh_str:
                        start_hm = "18:30"
                    elif "08:00-14:00" in oh_str:
                        start_hm = "10:00"
                    else:
                        start_hm = "12:30" if slot_idx == 0 and day_idx > 0 else "19:30"
                elif day_idx == 0 and slot_idx == 0:
                    start_hm = "14:00"
                elif day_idx == 0 and slot_idx == 1:
                    start_hm = "16:30"
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
        Assistant de voyage déterministe à règles (AI_CHAT_STRATEGY=rules) :
        - Synonymes (ajouter, mettre, rajouter, déplacer, décaler, changer, modifier, retirer, supprimer, annuler).
        - Correspondance approximative des noms de lieux (fautes de frappe, espaces collés, articles manquants).
        - Pronoms (le, la, ça) liés au dernier lieu cité.
        - Jours nommés, dates françaises (avec tolérance aux fautes sur les mois), heures ("14h", "14h30").
        - Questions d'information (autres lieux, météo, budget, horaires).
        - En cas d'incompréhension ou d'hésitation : question de clarification explicite,
          jamais de proposition au hasard ni de résumé hors sujet.
        """
        fr_weekdays = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        fr_months = [
            "",
            "janvier",
            "février",
            "mars",
            "avril",
            "mai",
            "juin",
            "juillet",
            "août",
            "septembre",
            "octobre",
            "novembre",
            "décembre",
        ]

        def _fmt_date_fr(iso_str: str) -> str:
            try:
                d = date.fromisoformat(str(iso_str)[:10])
                return f"{fr_weekdays[d.weekday()]} {d.day} {fr_months[d.month]}"
            except Exception:
                return str(iso_str)

        def _norm_text(s: str) -> str:
            s_clean = str(s).lower().replace("œ", "oe").replace("æ", "ae")
            s_decomposed = unicodedata.normalize("NFD", s_clean)
            s_no_accents = "".join(c for c in s_decomposed if unicodedata.category(c) != "Mn")
            return re.sub(r"[^a-z0-9]+", " ", s_no_accents).strip()

        def _spaceless(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", "", _norm_text(s))

        msg_lower = user_message.lower().strip()
        msg_norm = _norm_text(user_message)
        msg_spaceless = _spaceless(user_message)

        trip_info = safe_trip_context.get("trip", {})
        city_name = trip_info.get("city_name", "votre destination")
        itinerary_items: list[dict[str, Any]] = safe_trip_context.get("itinerary", [])
        available_places: list[dict[str, Any]] = safe_trip_context.get("available_places", [])
        flight_info = safe_trip_context.get("flight")
        acc_info = safe_trip_context.get("accommodation")
        budget_info = safe_trip_context.get("budget", {})
        weather_list: list[dict[str, Any]] = safe_trip_context.get("weather", [])

        # Liste chronologique des dates du séjour
        trip_dates_iso: list[str] = [
            str(w["date"])[:10] for w in weather_list if w.get("date")
        ]
        if not trip_dates_iso:
            arr_raw = str(trip_info.get("arrival_at") or "")[:10]
            dep_raw = str(trip_info.get("departure_at") or "")[:10]
            try:
                if arr_raw and dep_raw:
                    d_cur = date.fromisoformat(arr_raw)
                    d_end = date.fromisoformat(dep_raw)
                    while d_cur <= d_end:
                        trip_dates_iso.append(d_cur.isoformat())
                        d_cur += timedelta(days=1)
            except Exception:
                pass
        if not trip_dates_iso:
            trip_dates_iso = [date.today().isoformat()]

        def _resolve_named_date(raw_msg: str) -> str | None:
            lower = raw_msg.lower()
            # 1. Date ISO explicite (YYYY-MM-DD)
            iso_m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", raw_msg)
            if iso_m:
                return iso_m.group(1)

            base_d = date.fromisoformat(trip_dates_iso[0])
            trip_date_objs = [date.fromisoformat(x) for x in trip_dates_iso]

            # 2. Jours relatifs ("après-demain", "demain", "aujourd'hui")
            if re.search(r"\bapr[èe]s[- ]demain\b", lower):
                return (
                    trip_dates_iso[2]
                    if len(trip_dates_iso) > 2
                    else (base_d + timedelta(days=2)).isoformat()
                )
            if re.search(r"\bdemain\b", lower):
                return (
                    trip_dates_iso[1]
                    if len(trip_dates_iso) > 1
                    else (base_d + timedelta(days=1)).isoformat()
                )
            if re.search(r"\baujourd['’ ]?hui\b", lower):
                return trip_dates_iso[0]

            # 3. Numéro de jour ("jour 2", "jour 3")
            jour_m = re.search(r"\bjour\s*(\d{1,2})\b", lower)
            if jour_m:
                idx = int(jour_m.group(1)) - 1
                if 0 <= idx < len(trip_dates_iso):
                    return trip_dates_iso[idx]

            # 4. Format numérique DD/MM ou DD/MM/YYYY
            slash_m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?\b", lower)
            if slash_m:
                day_num = int(slash_m.group(1))
                month_num = int(slash_m.group(2))
                year_num = int(slash_m.group(3)) if slash_m.group(3) else base_d.year
                for d_obj in trip_date_objs:
                    if d_obj.day == day_num and d_obj.month == month_num:
                        return d_obj.isoformat()
                try:
                    return date(year_num, month_num, day_num).isoformat()
                except ValueError:
                    pass

            # 5. Date française "13 novembre", "13 novmbre" (correspondance exacte + approximative sur le mois)
            month_canonical: list[tuple[str, int]] = [
                ("janvier", 1),
                ("janv", 1),
                ("fevrier", 2),
                ("fevr", 2),
                ("mars", 3),
                ("avril", 4),
                ("avr", 4),
                ("mai", 5),
                ("juin", 6),
                ("juillet", 7),
                ("juil", 7),
                ("aout", 8),
                ("septembre", 9),
                ("sept", 9),
                ("octobre", 10),
                ("oct", 10),
                ("novembre", 11),
                ("nov", 11),
                ("decembre", 12),
                ("dec", 12),
            ]
            non_month_after_num = {
                "heure", "heures", "min", "minutes", "minute", "fois", "jour", "jours",
                "personne", "personnes", "euro", "euros", "an", "ans",
            }
            for dm_m in re.finditer(
                r"\b(\d{1,2})(?:er)?\s+([a-zàâçéèêëîïôûùüÿñæœ]{3,12})\b",
                lower,
            ):
                day_num = int(dm_m.group(1))
                if not (1 <= day_num <= 31):
                    continue
                word_norm = _norm_text(dm_m.group(2))
                if not word_norm or word_norm in non_month_after_num or re.match(r"^\d", word_norm):
                    continue
                matched_month: int | None = None
                for m_name, m_idx in month_canonical:
                    if word_norm == m_name:
                        matched_month = m_idx
                        break
                if matched_month is None and len(word_norm) >= 4:
                    best_ratio = 0.0
                    for m_name, m_idx in month_canonical:
                        if len(m_name) < 4:
                            continue
                        ratio = SequenceMatcher(None, word_norm, m_name).ratio()
                        if ratio >= 0.74 and ratio > best_ratio:
                            best_ratio = ratio
                            matched_month = m_idx
                if matched_month is not None:
                    for d_obj in trip_date_objs:
                        if d_obj.day == day_num and d_obj.month == matched_month:
                            return d_obj.isoformat()
                    try:
                        return date(base_d.year, matched_month, day_num).isoformat()
                    except ValueError:
                        pass

            # 6. Nom de jour de la semaine ("lundi".."dimanche", avec tolérance aux fautes)
            weekday_map = {
                "lundi": 0,
                "mardi": 1,
                "mercredi": 2,
                "jeudi": 3,
                "vendredi": 4,
                "samedi": 5,
                "dimanche": 6,
            }
            wd_matches = re.findall(
                r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b",
                lower,
            )
            target_wd: int | None = None
            if wd_matches:
                target_wd = weekday_map[wd_matches[-1]]
            else:
                for tok in msg_norm.split():
                    if len(tok) < 5:
                        continue
                    for wd_name, wd_idx in weekday_map.items():
                        if SequenceMatcher(None, tok, wd_name).ratio() >= 0.84:
                            target_wd = wd_idx
            if target_wd is not None:
                for d_obj in trip_date_objs:
                    if d_obj.weekday() == target_wd:
                        return d_obj.isoformat()
                delta_days = (target_wd - base_d.weekday()) % 7
                return (base_d + timedelta(days=delta_days)).isoformat()

            return None

        named_date_str = _resolve_named_date(user_message)

        # Extraction d'une heure ("14h", "14h30", "14:30", "midi", "minuit") hors dates ISO et DD/MM
        msg_without_dates = re.sub(r"\b20\d{2}-\d{2}-\d{2}\b", " ", msg_lower)
        msg_without_dates = re.sub(r"\b\d{1,2}/\d{1,2}(?:/20\d{2})?\b", " ", msg_without_dates)
        extracted_time: str | None = None
        if re.search(r"\bmidi\b", msg_without_dates):
            extracted_time = "12:00"
        elif re.search(r"\bminuit\b", msg_without_dates):
            extracted_time = "00:00"
        else:
            time_match = re.search(
                r"\b(\d{1,2})\s*(?:h|heures?|:)\s*(\d{2})?\b",
                msg_without_dates,
            )
            if time_match:
                hh = int(time_match.group(1))
                mm = int(time_match.group(2) or "0")
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    extracted_time = f"{hh:02d}:{mm:02d}"

        # Correspondance approximative des noms de lieux (fautes de frappe, articles manquants, mots collés, mots de lieu en plus)
        MIN_PLACE_SIMILARITY_THRESHOLD = 0.65
        AMBIGUITY_SCORE_MARGIN = 0.12

        place_stopwords = {
            "le", "la", "les", "l", "de", "du", "des", "d", "au", "aux", "en", "et", "a",
            "un", "une", "sur", "dans", "pour", "par", "chez", "mon", "ma", "mes", "ton",
            "ta", "tes", "son", "sa", "ses", "notre", "votre", "leur", "el", "al", "ou",
        }
        location_qualifiers = {
            "medina", "marrakech", "maroc", "gueliz", "hivernage", "kasbah", "mellah",
            "mouassine", "aguedal", "palmeraie", "paris", "france", "rome", "italie",
            "tokyo", "japon", "new", "york",
        }
        generic_place_heads = {
            "palais", "jardin", "jardins", "musee", "museum", "place", "mosquee", "parc", "cafe",
            "restaurant", "tour", "quartier", "galerie", "cathedrale", "basilique",
            "chateau", "temple", "sanctuaire", "memorial", "pont", "marche", "hotel",
            "maison", "fondation", "centre", "opera", "theatre", "tombeaux", "medersa",
            "riad", "fontaine", "statue",
        }
        non_place_words = {
            "ajouter", "ajoute", "ajoutes", "rajouter", "rajoute", "rajoutes", "mettre",
            "mets", "planifier", "planifie", "programmer", "programme", "inserer",
            "insere", "visiter", "visite", "visites", "aller", "voir", "faire", "deplacer",
            "deplace", "deplaces", "decaler", "decale", "decales", "changer", "change",
            "changes", "modifier", "modifie", "modifies", "reporter", "reporte",
            "reprogrammer", "reprogramme", "retirer", "retire", "retires", "supprimer",
            "supprime", "supprimes", "annuler", "annule", "annules", "enlever", "enleve",
            "enleves", "effacer", "efface", "oter", "ote", "avancer", "avance", "reculer",
            "recule", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi",
            "dimanche", "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
            "aout", "septembre", "octobre", "novembre", "novmbre", "decembre", "demain",
            "apres", "aujourd", "hui", "jour", "jours", "heure", "heures", "matin", "midi",
            "soir", "nuit", "truc", "chose", "quelque", "peux", "peut", "veux", "voudrais",
            "aimerais", "souhaite", "stp", "svp", "plait", "please", "merci", "bonjour", "salut", "autres",
            "autre", "lieux", "lieu", "endroit", "endroits", "meteo", "temps", "budget",
            "horaires", "horaire", "ouvre", "ouverture", "ferme", "fermeture", "combien",
            "quels", "quelles", "quel", "quelle", "quoi", "est", "sont", "pas", "plus",
            "dans", "avec", "sans", "fois", "deuxieme", "seconde", "donne", "donner",
            "montre", "montrer", "liste", "lister", "suggere", "recommande", "conseille",
            "reste", "depense", "cout", "coute", "sejour", "voyage", "prevu", "prevue",
            "prevus", "prevues", "ouverture", "duree", "dure", "blablabla", "sais", "rien",
            "new", "york", "paris", "tokyo", "rome", "marrakech",
        }

        verb_met_used = bool(
            re.search(r"\b(?:on|il|elle|qui|ça|ca|je|tu)(?:\s+(?:le|la|les|l['’]|y|en))?\s+mets?\b", msg_lower)
        )
        raw_norm_tokens = msg_norm.split()
        fuzzy_month_indices: set[int] = set()
        for idx_tok, tok_val in enumerate(raw_norm_tokens):
            if idx_tok > 0 and re.match(r"^\d{1,2}(?:er)?$", raw_norm_tokens[idx_tok - 1]) and len(tok_val) >= 4:
                if any(
                    SequenceMatcher(None, tok_val, m_name).ratio() >= 0.75
                    for m_name in (
                        "janvier", "fevrier", "mars", "avril", "mai", "juin",
                        "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
                    )
                ):
                    fuzzy_month_indices.add(idx_tok)

        msg_tokens = [
            t for i_t, t in enumerate(raw_norm_tokens)
            if t and not t.isdigit() and not re.match(r"^\d+h\d*$", t) and i_t not in fuzzy_month_indices
        ]
        meaningful_msg_tokens = [
            t for t in msg_tokens
            if t not in place_stopwords
            and t not in non_place_words
            and not (t in ("met", "mets") and verb_met_used)
            and len(t) >= 3
        ]
        msg_core_place_tokens = [
            t for t in meaningful_msg_tokens if t not in location_qualifiers
        ]
        user_specific_tokens = [
            t for t in msg_core_place_tokens
            if t not in generic_place_heads
            and not any(SequenceMatcher(None, t, gh).ratio() >= 0.84 for gh in generic_place_heads)
        ]
        user_head_tokens = [
            t for t in msg_core_place_tokens if t in generic_place_heads
        ]

        def _score_place_candidate(cand_name: str) -> float:
            p_norm = _norm_text(cand_name)
            if not p_norm:
                return 0.0
            main_part = re.split(r"[\(\&]", cand_name)[0].strip()
            p_main_norm = _norm_text(main_part) or p_norm
            p_spaceless = _spaceless(cand_name)
            p_main_spaceless = _spaceless(main_part) or p_spaceless

            p_core_tokens = [t for t in p_norm.split() if t not in place_stopwords and len(t) >= 2]
            raw_main_core = [
                t for t in p_main_norm.split()
                if t not in place_stopwords and t not in location_qualifiers and len(t) >= 2
            ]
            if not raw_main_core or all(t in generic_place_heads for t in raw_main_core):
                p_main_core_tokens = (
                    [t for t in p_main_norm.split() if t not in place_stopwords and len(t) >= 2]
                    or list(p_core_tokens)
                )
            else:
                p_main_core_tokens = raw_main_core

            p_specific_tokens = [
                t for t in p_core_tokens
                if t not in generic_place_heads and t not in location_qualifiers and len(t) >= 3
            ]
            if "metropolitan" in p_core_tokens and "met" not in p_specific_tokens:
                p_specific_tokens.append("met")
            if not p_specific_tokens:
                p_specific_tokens = [
                    t for t in p_core_tokens if t not in generic_place_heads and len(t) >= 3
                ] or list(p_main_core_tokens)

            p_core_spaceless = "".join(p_core_tokens)
            p_main_core_spaceless = "".join(p_main_core_tokens)

            # Synonymes et variantes locales courantes (ex: "sensoji" pour "senso-ji")
            for i in range(len(p_core_tokens) - 1):
                compound_tok = p_core_tokens[i] + p_core_tokens[i + 1]
                if len(compound_tok) >= 5 and compound_tok not in p_specific_tokens:
                    p_specific_tokens.append(compound_tok)

            user_spec_with_pairs = list(user_specific_tokens)
            for i in range(len(user_specific_tokens) - 1):
                user_spec_with_pairs.append(user_specific_tokens[i] + user_specific_tokens[i + 1])

            unmatched_user_spec = sum(
                1
                for ust in user_specific_tokens
                if not any(
                    ust == pst
                    or (len(ust) >= 4 and len(pst) >= 4 and (ust in pst or pst in ust))
                    or SequenceMatcher(None, ust, pst).ratio() >= 0.76
                    for pst in (p_specific_tokens + p_core_tokens)
                )
            )
            if user_specific_tokens and unmatched_user_spec == len(user_specific_tokens):
                pair_matched = any(
                    SequenceMatcher(None, upair, pst).ratio() >= 0.78
                    for upair in user_spec_with_pairs[len(user_specific_tokens) :]
                    for pst in (p_specific_tokens + p_core_tokens)
                )
                if not pair_matched:
                    return 0.0

            cand_head_tokens = [t for t in p_main_core_tokens if t in generic_place_heads]
            head_mismatch_penalty = (
                0.25
                if (
                    user_head_tokens
                    and cand_head_tokens
                    and not any(uh.rstrip("s") == ch.rstrip("s") for uh in user_head_tokens for ch in cand_head_tokens)
                )
                else 0.0
            )
            penalty = 0.14 * unmatched_user_spec + head_mismatch_penalty

            # 1. Sous-chaîne exacte normalisée (nom complet ou nom principal hors parenthèses)
            if p_norm in msg_norm:
                return max(0.0, 1.0 + len(p_norm) * 0.001 - penalty)
            if len(p_main_norm) >= 5 and p_main_norm in msg_norm:
                return max(0.0, 0.99 + len(p_main_norm) * 0.001 - penalty)

            p_main_core_str = " ".join(p_main_core_tokens)
            msg_core_str = " ".join(msg_core_place_tokens)
            if len(p_main_core_str) >= 5 and p_main_core_str in msg_core_str:
                return max(0.0, 0.97 + len(p_main_core_str) * 0.001 - penalty)

            # 2. Sous-chaîne sans espaces (ex: "Palaisde la bahia" -> "palaisdelabahia")
            if len(p_spaceless) >= 6 and p_spaceless in msg_spaceless:
                return max(0.0, 0.98 + len(p_spaceless) * 0.001 - penalty)
            if len(p_main_spaceless) >= 6 and p_main_spaceless in msg_spaceless:
                return max(0.0, 0.96 + len(p_main_spaceless) * 0.001 - penalty)
            if len(p_core_spaceless) >= 6 and p_core_spaceless in msg_spaceless:
                return max(0.0, 0.95 + len(p_core_spaceless) * 0.001 - penalty)
            if len(p_main_core_spaceless) >= 6 and p_main_core_spaceless in msg_spaceless:
                return max(0.0, 0.94 + len(p_main_core_spaceless) * 0.001 - penalty)

            if not meaningful_msg_tokens:
                return 0.0

            best_score = 0.0
            active_msg_pool = msg_core_place_tokens or meaningful_msg_tokens

            # 3. Correspondance par jetons spécifiques (ex: "secret", "bahia", "koutoubia", "menara", "majorele", "sadiens")
            for sp_tok in p_specific_tokens:
                if sp_tok in active_msg_pool or sp_tok in meaningful_msg_tokens:
                    matched_core = sum(
                        1
                        for ct in p_main_core_tokens
                        if any(SequenceMatcher(None, ct, mt).ratio() >= 0.80 for mt in msg_tokens)
                    )
                    best_score = max(best_score, 0.86 + 0.04 * matched_core - penalty)
                elif len(sp_tok) >= 4:
                    best_tok_ratio = max(
                        (SequenceMatcher(None, sp_tok, mt).ratio() for mt in active_msg_pool),
                        default=0.0,
                    )
                    # Vérifier aussi la concaténation de 2 jetons voisins si un mot a été coupé
                    for i in range(len(active_msg_pool) - 1):
                        joined_pair = active_msg_pool[i] + active_msg_pool[i + 1]
                        best_tok_ratio = max(best_tok_ratio, SequenceMatcher(None, sp_tok, joined_pair).ratio())
                    if best_tok_ratio >= 0.76:
                        matched_core = sum(
                            1
                            for ct in p_main_core_tokens
                            if any(SequenceMatcher(None, ct, mt).ratio() >= 0.75 for mt in msg_tokens)
                        )
                        best_score = max(best_score, 0.78 * best_tok_ratio + 0.05 * matched_core - penalty)

            # 4. Fenêtre glissante sur l'ensemble des jetons principaux du nom (hors mots géographiques en plus)
            if p_main_core_str and len(p_main_core_str) >= 5 and active_msg_pool:
                max_win = min(len(active_msg_pool), len(p_main_core_tokens) + 1)
                for w_len in range(1, max_win + 1):
                    for start_i in range(len(active_msg_pool) - w_len + 1):
                        win_str = " ".join(active_msg_pool[start_i : start_i + w_len])
                        ratio = SequenceMatcher(None, win_str, p_main_core_str).ratio()
                        if ratio >= 0.78:
                            best_score = max(best_score, ratio * 0.92 - penalty)

            # 5. Si aucun jeton spécifique n'a correspondu mais que l'utilisateur n'a donné qu'un terme générique
            #    (ex: "mets le Jardin le 13 novembre à 10h"), attribuer un score partiel sous le seuil (0.58)
            #    pour permettre la détection d'ambiguïté entre plusieurs lieux partageant ce type.
            if best_score < MIN_PLACE_SIMILARITY_THRESHOLD and not user_specific_tokens and msg_core_place_tokens:
                for gt in msg_core_place_tokens:
                    if gt in p_main_core_tokens:
                        best_score = max(best_score, 0.58)
                    elif any(gt.rstrip("s") == pt.rstrip("s") for pt in p_main_core_tokens):
                        best_score = max(best_score, 0.54)

            return max(0.0, best_score)

        def _clean_place_short_name(raw_name: str) -> str:
            cleaned = re.split(r"[\(\&]", str(raw_name or ""))[0].strip()
            return cleaned or str(raw_name or "").strip()

        def _format_place_du_de_la(raw_name: str) -> str:
            short = _clean_place_short_name(raw_name)
            low = short.lower()
            if low.startswith("le "):
                return f"du {short[3:].strip()}"
            if low.startswith("la "):
                return f"de la {short[3:].strip()}"
            if low.startswith("les "):
                return f"des {short[4:].strip()}"
            if low.startswith("l'") or low.startswith("l’"):
                return f"de l'{short[2:].strip()}"
            first_w = _norm_text(short.split()[0]) if short.split() else ""
            if first_w in {"jardin", "palais", "musee", "museum", "parc", "temple", "sanctuaire", "marche", "pont", "memorial", "centre", "chateau"}:
                return f"du {short}"
            if first_w in {"jardins", "tombeaux"}:
                return f"des {short}"
            return f"de {short}"

        def _format_ambiguous_places_question(name_a: str, name_b: str) -> str:
            return f"Vous parlez {_format_place_du_de_la(name_a)} ou {_format_place_du_de_la(name_b)} ?"

        scored_catalog_places: list[tuple[dict[str, Any], float]] = [
            (p, _score_place_candidate(str(p.get("name", ""))))
            for p in available_places
        ]
        scored_catalog_places.sort(
            key=lambda item: (
                -round(item[1], 3),
                0
                if "jardin secret" in _norm_text(str(item[0].get("name", "")))
                else (1 if "majorelle" in _norm_text(str(item[0].get("name", ""))) else 2),
                len(_clean_place_short_name(str(item[0].get("name", "")))),
            )
        )

        best_catalog_score = scored_catalog_places[0][1] if scored_catalog_places else 0.0
        second_catalog_score = scored_catalog_places[1][1] if len(scored_catalog_places) >= 2 else 0.0

        ambiguous_places_pair: tuple[dict[str, Any], dict[str, Any]] | None = None
        if len(scored_catalog_places) >= 2 and msg_core_place_tokens:
            p1_cand, sc1_val = scored_catalog_places[0]
            p2_cand, sc2_val = scored_catalog_places[1]
            if (
                sc1_val >= MIN_PLACE_SIMILARITY_THRESHOLD
                and sc2_val >= MIN_PLACE_SIMILARITY_THRESHOLD
                and (sc1_val - sc2_val) < AMBIGUITY_SCORE_MARGIN
                and not (sc1_val >= 0.99 and sc2_val < 0.95)
            ):
                ambiguous_places_pair = (p1_cand, p2_cand)
            elif (
                sc1_val < MIN_PLACE_SIMILARITY_THRESHOLD
                and sc1_val >= 0.50
                and sc2_val >= 0.50
                and (sc1_val - sc2_val) < AMBIGUITY_SCORE_MARGIN
            ):
                ambiguous_places_pair = (p1_cand, p2_cand)

        def _find_explicit_place_in_catalog() -> dict[str, Any] | None:
            if ambiguous_places_pair is not None:
                return None
            if scored_catalog_places and scored_catalog_places[0][1] >= MIN_PLACE_SIMILARITY_THRESHOLD:
                return scored_catalog_places[0][0]
            return None

        def _find_explicit_scheduled_item() -> dict[str, Any] | None:
            if ambiguous_places_pair is not None:
                return None
            best_item: dict[str, Any] | None = None
            best_sc = 0.0
            for item in itinerary_items:
                sc = _score_place_candidate(str(item.get("place_name", "")))
                if sc >= MIN_PLACE_SIMILARITY_THRESHOLD and sc > best_sc:
                    best_sc = sc
                    best_item = item
            if best_item is not None and best_sc + 0.04 < best_catalog_score:
                return None
            return best_item

        def _resolve_last_place_id() -> str | None:
            last_pid = safe_trip_context.get("last_place_id")
            if last_pid:
                return str(last_pid)
            last_pname = safe_trip_context.get("last_place_name")
            if last_pname:
                for p in available_places:
                    if str(p.get("name", "")).lower() == str(last_pname).lower():
                        return str(p.get("id"))
            for msg in reversed(chat_history):
                content_str = str(msg.get("content", ""))
                for p in available_places:
                    if str(p.get("name", "")).lower() in content_str.lower():
                        return str(p.get("id"))
            if itinerary_items:
                return str(itinerary_items[-1].get("place_id"))
            return None

        def _find_pronoun_scheduled_item() -> dict[str, Any] | None:
            last_pid = _resolve_last_place_id()
            if last_pid:
                for item in reversed(itinerary_items):
                    if str(item.get("place_id")) == last_pid:
                        return item
                return None
            return itinerary_items[-1] if itinerary_items else None

        def _find_pronoun_place_in_catalog() -> dict[str, Any] | None:
            last_pid = _resolve_last_place_id()
            if last_pid:
                for p in available_places:
                    if str(p.get("id")) == last_pid:
                        return p
            return None

        explicit_sched = _find_explicit_scheduled_item()
        explicit_catalog_place = _find_explicit_place_in_catalog()

        wants_second_time_early = bool(
            re.search(r"(deuxi[èe]me\s+fois|seconde\s+fois|une\s+autre\s+fois|encore\s+une\s+fois)", msg_lower)
        )
        # Détection stricte des pronoms (le, la, l', ça, cette visite, ce lieu) liés au dernier lieu cité :
        # "mets le Jardin Secret" n'est JAMAIS un pronom ("le" est l'article défini devant le nom du lieu).
        raw_pronoun_match = bool(
            re.search(
                r"(\b(on\s+le\s+met\w*|on\s+la\s+met\w*|on\s+l['’]\s*met\w*|on\s+le\s+d[ée]plac\w*|on\s+la\s+d[ée]plac\w*|"
                r"on\s+le\s+d[ée]cal\w*|on\s+la\s+d[ée]cal\w*|on\s+le\s+modifi\w*|on\s+la\s+modifi\w*|on\s+le\s+chang\w*|"
                r"on\s+le\s+supprim\w*|on\s+la\s+supprim\w*|on\s+le\s+retir\w*|on\s+la\s+retir\w*|on\s+l['’]\s*annul\w*|"
                r"on\s+l['’]\s*ajoute\w*|on\s+le\s+rajoute\w*|on\s+la\s+rajoute\w*|"
                r"je\s+le\s+met\w*|je\s+la\s+met\w*|je\s+le\s+d[ée]plac\w*|je\s+la\s+d[ée]plac\w*|"
                r"mets?-le|mets?-la|mettre\s+[çc]a|on\s+met\w*\s+[çc]a|mets?\s+[çc]a|"
                r"d[ée]placez?-le|d[ée]placez?-la|d[ée]placer?\s+[çc]a|"
                r"d[ée]calez?-le|d[ée]calez?-la|d[ée]caler?\s+[çc]a|"
                r"modifiez?-le|modifiez?-la|modifier?\s+[çc]a|"
                r"changez?-le|changez?-la|changer?\s+[çc]a|"
                r"retirez?-le|retirez?-la|retirer?\s+[çc]a|"
                r"supprimez?-le|supprimez?-la|supprimer?\s+[çc]a|"
                r"annulez?-le|annulez?-la|annuler?\s+[çc]a|"
                r"enl[èe]vez?-le|enl[èe]vez?-la|enlever?\s+[çc]a|"
                r"ajoutez?-le|ajoutez?-la|rajoutez?-le|rajoutez?-la|"
                r"cette\s+visite|ce\s+lieu|cet\s+endroit)\b)",
                msg_lower,
            )
        )
        has_pronoun_ref = bool(
            raw_pronoun_match and (not msg_core_place_tokens or wants_second_time_early)
        )

        # Détection des familles de verbes (synonymes)
        has_remove_verb = bool(
            re.search(
                r"\b(retirer|retire|retires|retirez|supprimer|supprime|supprimes|supprimez|"
                r"annuler|annule|annules|annulez|enlever|enl[èe]ve|enl[èe]ves|enlevez|"
                r"effacer|efface|effacez|[ôo]ter|[ôo]te|[ôo]tez)\b",
                msg_lower,
            )
        )
        has_move_verb = bool(
            re.search(
                r"\b(d[ée]placer|d[ée]place|d[ée]places|d[ée]placez|d[ée]caler|d[ée]cale|d[ée]cales|d[ée]calez|"
                r"changer|change|changes|changez|modifier|modifie|modifies|modifiez|"
                r"reporter|reporte|reportes|reportez|reprogrammer|reprogramme|reprogrammez|"
                r"avancer|avance|avancez|reculer|recule|reculez)\b",
                msg_lower,
            )
        )
        has_explicit_add_verb = bool(
            re.search(
                r"\b(ajouter|ajoute|ajoutes|ajoutez|rajouter|rajoute|rajoutes|rajoutez|"
                r"planifier|planifie|planifies|planifiez|programmer|programme|programmes|programmez|"
                r"ins[ée]rer|ins[èe]re|ins[èe]res|visiter|visite)\b",
                msg_lower,
            )
        ) and not has_move_verb and not has_remove_verb
        has_put_or_go_verb = (
            bool(
                re.search(
                    r"\b(mettre|mets|mettez|aller\s+voir|aller\s+[àa]|aller\s+au|aller\s+aux|on\s+va\s+voir)\b",
                    msg_lower,
                )
            )
            or verb_met_used
        ) and not has_move_verb and not has_remove_verb

        # ---------------------------------------------------------------------
        # 00. COMMANDES VOCALES DE NAVIGATION, LECTURE (ÉTAPE 5V & 5A)
        #     ET ACTIONS SENSIBLES À DOUBLE CONFIRMATION (RÉSERVATION, PAIEMENT)
        # ---------------------------------------------------------------------
        # 00a. Lecture vocale d'un jour précis : "lis-moi le jour 2", "lis le jour 1"
        day_read_match = re.search(
            r"\b(?:lis(?:[- ]moi)?|lisez(?:[- ]moi)?|lecture(?:\s+du)?|raconte(?:[- ]moi)?)\s+"
            r"(?:le\s+|mon\s+)?jour\s*(\d+|un|deux|trois|quatre|cinq|six|sept)\b",
            msg_lower,
        )
        if day_read_match:
            word_to_num = {
                "un": 1,
                "deux": 2,
                "trois": 3,
                "quatre": 4,
                "cinq": 5,
                "six": 6,
                "sept": 7,
            }
            raw_tok = day_read_match.group(1)
            day_num = word_to_num.get(raw_tok, int(raw_tok) if raw_tok.isdigit() else 1)
            day_idx = max(0, min(day_num - 1, len(trip_dates_iso) - 1))
            target_day_iso = trip_dates_iso[day_idx]
            day_items = [
                it for it in itinerary_items if str(it.get("visit_date", ""))[:10] == target_day_iso
            ]
            day_items.sort(key=lambda x: str(x.get("local_start_time", "00:00")))
            if day_items:
                segments = [
                    f"à {it.get('local_start_time', '10:00')}, {it.get('place_name', 'Visite')} ({it.get('duration_minutes', 90)} minutes)"
                    for it in day_items
                ]
                day_reply = (
                    f"Lecture vocale du jour {day_num} ({_fmt_date_fr(target_day_iso)}) à {city_name} : "
                    f"{len(day_items)} visite(s) au programme — " + " ; puis ".join(segments) + "."
                )
            else:
                day_reply = (
                    f"Lecture vocale du jour {day_num} ({_fmt_date_fr(target_day_iso)}) à {city_name} : "
                    "aucune visite n'est encore planifiée sur cette journée."
                )
            return {
                "action_type": "READ_DAY",
                "voice_command": "READ_DAY",
                "navigation_target": "/itinerary",
                "day_number": day_num,
                "place_name": None,
                "visit_date": target_day_iso,
                "local_start_time": None,
                "reply": day_reply,
                "proposed_action": None,
            }

        # 00b. Écran 5A Budget : "lis-moi mon budget", "ouvre mon budget", "va à mon budget"
        is_voice_budget_cmd = bool(
            re.search(
                r"\b(?:lis(?:[- ]moi)?|lisez(?:[- ]moi)?|lecture(?:\s+de)?|ouvre|ouvrir|"
                r"va\s+(?:[àa]|au|vers|sur)|aller\s+(?:[àa]|au|vers|sur)|affiche|afficher)\s+"
                r"(?:mon\s+|le\s+)?budget\b",
                msg_lower,
            )
        )
        if is_voice_budget_cmd:
            budget_total = budget_info.get("planned_total", trip_info.get("total_budget_planned", 2000))
            spent_total = budget_info.get(
                "total_spent",
                budget_info.get("committed_total", budget_info.get("flight_cost", 0)),
            )
            rem_total = budget_info.get(
                "remaining_total",
                budget_info.get("remaining_estimated", max(0, float(budget_total) - float(spent_total))),
            )
            currency = trip_info.get("currency", "EUR")
            alert_msg = budget_info.get("alert_message_fr") or ""
            cat_summary = budget_info.get("categories_summary_fr") or ""
            reply_budget = (
                f"Lecture vocale de votre budget pour {city_name} : budget total prévu de {float(budget_total):.2f} {currency}, "
                f"total dépensé {float(spent_total):.2f} {currency}, solde restant {float(rem_total):.2f} {currency}."
            )
            if cat_summary:
                reply_budget += f" Répartition : {cat_summary}."
            if alert_msg:
                reply_budget += f" {alert_msg}"
            return {
                "action_type": "READ_BUDGET",
                "voice_command": "READ_BUDGET",
                "navigation_target": "/trip/budget",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": reply_budget,
                "proposed_action": None,
            }

        # 00c. Écran 5A Documents : "ouvre mes documents", "va à mes documents", "lis-moi mes documents"
        is_voice_documents_cmd = bool(
            re.search(
                r"\b(?:(?:ouvre|ouvrir|va\s+(?:[àa]|aux|vers|sur)|aller\s+(?:[àa]|aux|vers|sur)|"
                r"lis(?:[- ]moi)?|affiche|afficher)\s+(?:mes\s+|les\s+)?documents?|\bmes\s+documents?\b)",
                msg_lower,
            )
        )
        if is_voice_documents_cmd:
            docs_meta = safe_trip_context.get("documents_summary") or {}
            doc_count = int(docs_meta.get("visible_count", 0))
            titles_list = docs_meta.get("titles") or []
            passport_msg = docs_meta.get("passport_alert_message_fr")
            if doc_count > 0:
                titles_str = ", ".join(str(t) for t in titles_list[:4])
                reply_docs = (
                    f"Ouverture de vos documents pour {city_name} : vous avez {doc_count} document(s) chiffré(s) "
                    f"accessible(s) ({titles_str})."
                )
            else:
                reply_docs = (
                    f"Ouverture de vos documents pour {city_name} : aucun document enregistré pour le moment."
                )
            if passport_msg:
                reply_docs += f" {passport_msg}"
            return {
                "action_type": "OPEN_DOCUMENTS",
                "voice_command": "OPEN_DOCUMENTS",
                "navigation_target": "/trip/documents",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": reply_docs,
                "proposed_action": None,
            }

        # 00d. Écran 5A Infos pratiques : "infos pratiques", "ouvre les infos pratiques", "lis-moi les infos pratiques"
        is_voice_practical_cmd = bool(
            re.search(r"\b(infos?\s+pratiques?|informations?\s+pratiques?)\b", msg_lower)
        )
        if is_voice_practical_cmd:
            p_info = safe_trip_context.get("practical_info") or {}
            plugs = p_info.get("plugs") or "Type C / E"
            emerg = p_info.get("emergency") or "112"
            curr_label = p_info.get("currency") or trip_info.get("currency", "EUR")
            dial = p_info.get("dial_code") or "+33"
            tipping = p_info.get("tipping") or "Selon satisfaction"
            reply_practical = (
                f"Infos pratiques pour {city_name} : prises électriques {plugs}. "
                f"Urgences : {emerg}. Monnaie : {curr_label} (indicatif {dial}). "
                f"Pourboires : {tipping}."
            )
            return {
                "action_type": "OPEN_PRACTICAL_INFO",
                "voice_command": "OPEN_PRACTICAL_INFO",
                "navigation_target": "/trip/infos",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": reply_practical,
                "proposed_action": None,
            }

        # 00e. Commandes de navigation vocales : "va à mon programme", "ouvre l'hébergement", etc.
        is_nav_programme = bool(
            re.search(
                r"\b(?:va\s+(?:[àa]|au|vers|sur)|aller\s+(?:[àa]|au|vers|sur)|ouvre|ouvrir|affiche|afficher|"
                r"retourne\s+(?:[àa]|au))\s+(?:mon\s+|le\s+)?programme\b",
                msg_lower,
            )
        )
        if is_nav_programme:
            return {
                "action_type": "NAVIGATE",
                "voice_command": "NAVIGATE_ITINERARY",
                "navigation_target": "/itinerary",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": (
                    f"Navigation vocale vers votre programme à {city_name}. "
                    f"Vous avez {len(itinerary_items)} visite(s) planifiée(s)."
                ),
                "proposed_action": None,
            }

        is_nav_accommodation = bool(
            re.search(
                r"\b(?:ouvre|ouvrir|va\s+(?:[àa]|aux|vers|sur)|aller\s+(?:[àa]|aux|vers|sur)|"
                r"affiche|afficher|montre|montrer)\s+(?:l['’]\s*|les\s+|mon\s+)?(h[ée]bergements?|h[ôo]tels?|logements?)\b",
                msg_lower,
            )
        )
        if is_nav_accommodation:
            acc_info = safe_trip_context.get("accommodation") or {}
            acc_name = acc_info.get("name")
            acc_suffix = f" Hébergement recommandé : {acc_name}." if acc_name else ""
            return {
                "action_type": "NAVIGATE",
                "voice_command": "NAVIGATE_ACCOMMODATIONS",
                "navigation_target": "/accommodations",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": f"Ouverture de l'écran des hébergements à {city_name}.{acc_suffix}",
                "proposed_action": None,
            }

        is_nav_trip_hub = bool(
            re.search(
                r"\b(?:va\s+(?:[àa]|vers|sur)|aller\s+(?:[àa]|vers|sur)|ouvre|ouvrir|affiche|afficher)\s+"
                r"(?:mon\s+|le\s+)?voyage\b",
                msg_lower,
            )
        )
        if is_nav_trip_hub:
            return {
                "action_type": "NAVIGATE",
                "voice_command": "NAVIGATE_TRIP",
                "navigation_target": "/trip",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": f"Ouverture de l'accueil Mon voyage pour {city_name}.",
                "proposed_action": None,
            }

        is_nav_flights = bool(
            re.search(
                r"\b(?:ouvre|ouvrir|va\s+(?:[àa]|aux|vers|sur)|aller\s+(?:[àa]|aux|vers|sur)|"
                r"affiche|afficher)\s+(?:les\s+|mes\s+|mon\s+)?vols?\b",
                msg_lower,
            )
        )
        if is_nav_flights:
            return {
                "action_type": "NAVIGATE",
                "voice_command": "NAVIGATE_FLIGHTS",
                "navigation_target": "/flights",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": f"Ouverture de l'écran des vols pour {city_name}.",
                "proposed_action": None,
            }

        is_nav_activities = bool(
            re.search(
                r"\b(?:ouvre|ouvrir|va\s+(?:[àa]|aux|vers|sur)|aller\s+(?:[àa]|aux|vers|sur)|"
                r"affiche|afficher)\s+(?:les\s+|mes\s+)?activit[ée]s?\b",
                msg_lower,
            )
        )
        if is_nav_activities:
            return {
                "action_type": "NAVIGATE",
                "voice_command": "NAVIGATE_ACTIVITIES",
                "navigation_target": "/activities",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": f"Ouverture du catalogue des activités à {city_name}.",
                "proposed_action": None,
            }

        is_nav_settings = bool(
            re.search(
                r"\b(?:ouvre|ouvrir|va\s+(?:[àa]|aux|vers|sur)|aller\s+(?:[àa]|aux|vers|sur)|"
                r"affiche|afficher)\s+(?:les\s+|mes\s+)?param[èe]tres?\b",
                msg_lower,
            )
        )
        if is_nav_settings:
            return {
                "action_type": "NAVIGATE",
                "voice_command": "NAVIGATE_SETTINGS",
                "navigation_target": "/settings",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": "Ouverture des paramètres et des options d'accessibilité vocale.",
                "proposed_action": None,
            }

        # 00f. Actions sensibles soumises à DOUBLE CONFIRMATION vocale : Réservation & Paiement
        is_booking_command = bool(
            re.search(
                r"\b(r[ée]server|r[ée]serve|r[ée]servez|confirmer?\s+la\s+r[ée]servation)\b",
                msg_lower,
            )
        )
        if is_booking_command:
            acc_info = safe_trip_context.get("accommodation") or {}
            flight_info = safe_trip_context.get("flight") or {}
            if "vol" in msg_lower or "avion" in msg_lower:
                booking_label = (
                    f"Vol {flight_info.get('airline', 'Air France')} ({city_name})"
                )
            else:
                booking_label = acc_info.get("name") or f"Hébergement sélectionné à {city_name}"
            first_place_id = (
                str(available_places[0]["id"]) if available_places else "reservation-target"
            )
            return {
                "action_type": "BOOK_RESERVATION",
                "place_name": booking_label,
                "visit_date": trip_dates_iso[0],
                "local_start_time": "14:00",
                "reply": (
                    f"Action comprise : réserver « {booking_label} » pour votre séjour à {city_name}. "
                    "Cette réservation nécessite une double confirmation vocale. "
                    "Première confirmation : dites « oui » pour confirmer, ou « non » (ou gardez le silence) pour annuler."
                ),
                "proposed_action": {
                    "action_type": "BOOK_RESERVATION",
                    "item_id": None,
                    "place_id": first_place_id,
                    "place_name": booking_label,
                    "visit_date": trip_dates_iso[0],
                    "local_start_time": "14:00",
                    "duration_minutes": 60,
                    "transit_mode": "METRO",
                    "requires_double_confirmation": True,
                    "confirmation_steps_required": 2,
                    "confirmation_step": 1,
                },
            }

        is_payment_command = bool(
            re.search(
                r"\b(payer|paie|paye|payez|effectuer?\s+le\s+paiement|valider?\s+le\s+paiement|"
                r"r[ée]gler\s+(?:la\s+r[ée]servation|le\s+s[ée]jour|l['’]h[ôo]tel|le\s+vol))\b",
                msg_lower,
            )
        )
        if is_payment_command:
            budget_total = budget_info.get("planned_total", trip_info.get("total_budget_planned", 2000))
            currency = trip_info.get("currency", "EUR")
            payment_label = f"Paiement réservation séjour {city_name} ({budget_total} {currency})"
            first_place_id = (
                str(available_places[0]["id"]) if available_places else "payment-target"
            )
            return {
                "action_type": "PROCESS_PAYMENT",
                "place_name": payment_label,
                "visit_date": trip_dates_iso[0],
                "local_start_time": "12:00",
                "reply": (
                    f"Action comprise : effectuer le « {payment_label} ». "
                    "Ce paiement nécessite une double confirmation vocale. "
                    "Première confirmation : dites « oui » pour confirmer, ou « non » (ou gardez le silence) pour annuler."
                ),
                "proposed_action": {
                    "action_type": "PROCESS_PAYMENT",
                    "item_id": None,
                    "place_id": first_place_id,
                    "place_name": payment_label,
                    "visit_date": trip_dates_iso[0],
                    "local_start_time": "12:00",
                    "duration_minutes": 30,
                    "transit_mode": "METRO",
                    "requires_double_confirmation": True,
                    "confirmation_steps_required": 2,
                    "confirmation_step": 1,
                },
            }

        # ---------------------------------------------------------------------
        # 0. QUESTIONS D'INFORMATION (Action INFO : autres lieux, horaires, météo, budget)
        # ---------------------------------------------------------------------
        # 0a. Autres lieux à visiter non présents au programme
        has_hesitation_negation = bool(
            re.search(r"\b(je\s+ne\s+sais\s+pas|je\s+sais\s+pas\s+trop|sais\s+pas\s+quoi)\b", msg_lower)
        )
        is_places_info_question = not has_hesitation_negation and bool(
            re.search(
                r"(autres?\s+lieux?|d['’]autres?\s+(lieux|endroits|visites|id[ée]es)|"
                r"pas\s+(encore\s+)?(mis|ajout[ée]|planifi[ée]|pr[ée]vu)?\s*(dans|au)\s+(mon\s+|le\s+)?programme|"
                r"(quels?|quelles?)\s+(sont\s+les\s+)?(autres\s+)?(lieux|visites|activit[ée]s|endroits|monuments|mus[ée]es|restaurants)|"
                r"(que|quoi)\s+(puis[- ]je|je\s+peux|peut[- ]on|on\s+peut)\s*(visiter|voir|faire)(\s+d['’]autre)?|"
                r"(donne|donner|montre|montrer|liste|lister|sugg[èe]re|conseille|recommande)\b.*\b(lieux|visites|endroits|id[ée]es|activit[ée]s)|"
                r"\bid[ée]es?\s+de\s+(visites?|lieux|sorties?)\b)",
                msg_lower,
            )
        )
        if is_places_info_question and not has_move_verb and not has_remove_verb:
            scheduled_ids = {str(it.get("place_id")) for it in itinerary_items if it.get("place_id")}
            cat_map_fr = {
                "CULTURE": "Culture",
                "MUSEUM": "Culture",
                "MONUMENT": "Culture",
                "NATURE": "Nature",
                "PARK": "Nature",
                "RESTAURANT": "Restaurant",
                "FOOD": "Restaurant",
                "NIGHTLIFE": "Vie nocturne",
                "NIGHT": "Vie nocturne",
            }
            unscheduled_lines: list[str] = []
            for p in available_places:
                if str(p.get("id")) in scheduled_ids:
                    continue
                cat_fr = cat_map_fr.get(str(p.get("category", "")).upper(), str(p.get("category", "Culture")).capitalize())
                env_fr = "Extérieur" if p.get("is_outdoor") else "Intérieur"
                dur_min = int(p.get("recommended_duration_min", 90))
                unscheduled_lines.append(f"• {p.get('name')} — {cat_fr}, durée conseillée : {dur_min} min, {env_fr}")

            if unscheduled_lines:
                reply_txt = (
                    f"Voici d'autres lieux à visiter à {city_name} qui ne sont pas dans votre programme :\n"
                    + "\n".join(unscheduled_lines)
                    + "\n\nSouhaitez-vous en ajouter un à votre programme ? Indiquez-moi son nom ainsi que le jour et l'heure souhaités."
                )
            else:
                reply_txt = f"Tous les lieux enregistrés à {city_name} figurent déjà dans votre programme."

            return {
                "action_type": "INFO",
                "info_subtype": "PLACES",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": reply_txt,
                "proposed_action": None,
            }

        # 0b. Question sur les horaires / durée d'ouverture d'un lieu
        is_hours_info_question = bool(
            re.search(
                r"\b(horaires?|ouvre|ouverture|ferme|fermeture|[àa]\s+quelle\s+heure\s+(ouvre|ferme)|"
                r"combien\s+de\s+temps\s+dure|dur[ée]e\s+(conseill[ée]e|de\s+visite))\b",
                msg_lower,
            )
        )
        if is_hours_info_question and not has_move_verb and not has_remove_verb and not has_explicit_add_verb:
            info_place = explicit_catalog_place or _find_pronoun_place_in_catalog()
            if info_place is not None:
                dur_min = int(info_place.get("recommended_duration_min", 90))
                env_fr = "Extérieur" if info_place.get("is_outdoor") else "Intérieur"
                oh = info_place.get("opening_hours") or {}
                hours_str = "09:00 - 18:00"
                if isinstance(oh, dict) and oh:
                    first_val = next(iter(oh.values()))
                    if isinstance(first_val, dict):
                        hours_str = f"{first_val.get('open', '09:00')} - {first_val.get('close', '18:00')}"
                    elif isinstance(first_val, str):
                        hours_str = first_val
                return {
                    "action_type": "INFO",
                    "info_subtype": "HOURS",
                    "place_name": str(info_place.get("name")),
                    "visit_date": None,
                    "local_start_time": None,
                    "reply": (
                        f"Horaires indicatifs pour « {info_place.get('name')} » : {hours_str} "
                        f"({env_fr}, durée conseillée : {dur_min} min)."
                    ),
                    "proposed_action": None,
                }
            return {
                "action_type": "INFO",
                "info_subtype": "HOURS",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": (
                    f"Les lieux culturels et jardins à {city_name} sont généralement ouverts de 09:00 à 18:00. "
                    "Précisez le nom d'un lieu pour connaître sa durée conseillée et ses horaires."
                ),
                "proposed_action": None,
            }

        # 0c. Question sur la météo ou le budget (ou point météo/budget)
        is_weather_or_budget_question = bool(
            re.search(
                r"\b(m[ée]t[ée]o|quel\s+temps|pleuvoir|pluie|temp[ée]rature|ensoleill[ée]|"
                r"budget|d[ée]pens[ée]s?|combien\s+(il\s+me\s+reste|co[ûu]te|ai[- ]je\s+d[ée]pens[ée])|"
                r"co[ûu]t\s+du\s+s[ée]jour|point\s+m[ée]t[ée]o|point\s+budget)\b",
                msg_lower,
            )
        )
        if is_weather_or_budget_question and not has_move_verb and not has_remove_verb and not has_explicit_add_verb:
            budget_total = budget_info.get("planned_total", trip_info.get("total_budget_planned", 2000))
            committed = budget_info.get("committed_total", 0)
            remaining = budget_info.get("remaining_total", budget_total)
            currency = trip_info.get("currency", "EUR")
            if weather_list:
                target_w = weather_list[0]
                if named_date_str:
                    for w in weather_list:
                        if str(w.get("date", ""))[:10] == named_date_str:
                            target_w = w
                            break
                w_label = target_w.get("condition_label_fr") or target_w.get("summary", "Ensoleillé")
                w_temp = target_w.get("temp_max_c") or target_w.get("temperature_celsius", 22)
                w_date_fr = _fmt_date_fr(str(target_w.get("date", trip_dates_iso[0]))[:10])
                weather_brief = f"{w_label} ({w_temp}°C) le {w_date_fr}"
            else:
                weather_brief = "prévisions météo en cours de chargement"

            return {
                "action_type": "INFO",
                "info_subtype": "WEATHER_BUDGET",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": (
                    f"Point séjour à {city_name} — Météo : {weather_brief}. "
                    f"Budget prévu : {budget_total} {currency} (engagé : {committed} {currency}, "
                    f"restant : {remaining} {currency}). "
                    f"Vous avez actuellement {len(itinerary_items)} visite(s) planifiée(s)."
                ),
                "proposed_action": None,
            }

        if ambiguous_places_pair is not None:
            return {
                "action_type": "ASK",
                "ask_reason": "AMBIGUOUS_PLACE",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": _format_ambiguous_places_question(
                    str(ambiguous_places_pair[0].get("name", "")),
                    str(ambiguous_places_pair[1].get("name", "")),
                ),
                "proposed_action": None,
            }

        def _build_unrecognized_or_unknown_place_reply() -> dict[str, Any]:
            if user_specific_tokens or msg_core_place_tokens:
                return {
                    "action_type": "ASK",
                    "ask_reason": "UNKNOWN_PLACE",
                    "place_name": None,
                    "visit_date": None,
                    "local_start_time": None,
                    "reply": f"Je ne trouve pas ce lieu à {city_name}. De quel lieu parlez-vous ?",
                    "proposed_action": None,
                }
            return {
                "action_type": "ASK",
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": "Je n'ai pas compris. Voulez-vous ajouter, déplacer ou retirer une visite ?",
                "proposed_action": None,
            }

        # ---------------------------------------------------------------------
        # 1. INTENTION : SUPPRIMER / RETIRER / ANNULER UNE VISITE
        # ---------------------------------------------------------------------
        if has_remove_verb:
            target_item = explicit_sched or (_find_pronoun_scheduled_item() if has_pronoun_ref else None)
            if target_item is not None:
                return {
                    "action_type": "REMOVE_VISIT",
                    "place_name": target_item["place_name"],
                    "visit_date": target_item["visit_date"],
                    "local_start_time": target_item["local_start_time"],
                    "reply": (
                        f"Je peux retirer la visite « {target_item['place_name']} » prévue le "
                        f"{_fmt_date_fr(target_item['visit_date'])} à {target_item['local_start_time']}. "
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
                        "requires_double_confirmation": True,
                        "confirmation_steps_required": 2,
                        "confirmation_step": 1,
                    },
                }
            if explicit_catalog_place is not None:
                return {
                    "action_type": "ASK",
                    "place_name": explicit_catalog_place["name"],
                    "visit_date": None,
                    "local_start_time": None,
                    "reply": (
                        f"La visite « {explicit_catalog_place['name']} » ne figure pas dans votre programme actuel. "
                        "Quelle visite souhaitez-vous retirer ?"
                    ),
                    "proposed_action": None,
                }
            return _build_unrecognized_or_unknown_place_reply()

        # ---------------------------------------------------------------------
        # 2. INTENTION : DÉPLACER / DÉCALER / MODIFIER / CHANGER UNE VISITE
        # ---------------------------------------------------------------------
        is_move_intent = (
            has_move_verb
            or (has_pronoun_ref and not has_explicit_add_verb)
            or (
                explicit_sched is not None
                and not has_explicit_add_verb
                and (named_date_str is not None or extracted_time is not None)
            )
        )
        if is_move_intent:
            target_item = explicit_sched or (_find_pronoun_scheduled_item() if has_pronoun_ref else None)
            if target_item is not None:
                if named_date_str is None and extracted_time is None:
                    return {
                        "action_type": "ASK",
                        "place_name": target_item["place_name"],
                        "visit_date": None,
                        "local_start_time": None,
                        "reply": (
                            f"À quel jour et à quelle heure souhaitez-vous déplacer « {target_item['place_name']} » ?"
                        ),
                        "proposed_action": None,
                    }
                new_date = named_date_str if named_date_str else target_item["visit_date"]
                new_time = extracted_time if extracted_time else target_item["local_start_time"]
                sim_score = (
                    round(_score_place_candidate(str(target_item.get("place_name", ""))), 3)
                    if explicit_sched is not None
                    else 0.85
                )
                return {
                    "action_type": "MOVE_VISIT",
                    "place_name": target_item["place_name"],
                    "visit_date": new_date,
                    "local_start_time": new_time,
                    "place_similarity_score": sim_score,
                    "explicit_date": bool(named_date_str is not None),
                    "explicit_time": bool(extracted_time is not None),
                    "reply": (
                        f"Je vous propose de déplacer « {target_item['place_name']} » au "
                        f"{_fmt_date_fr(new_date)} à {new_time}. Souhaitez-vous appliquer ce changement ?"
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
                        "place_similarity_score": sim_score,
                        "explicit_date": bool(named_date_str is not None),
                        "explicit_time": bool(extracted_time is not None),
                    },
                }

            # Si l'utilisateur emploie un verbe de modification ("modifier Palais de la Bahia le 13 novembre à 12h")
            # sur un lieu connu du catalogue qui n'est pas encore planifié :
            target_unscheduled = explicit_catalog_place or (
                _find_pronoun_place_in_catalog() if has_pronoun_ref else None
            )
            if target_unscheduled is not None:
                if named_date_str is None:
                    return {
                        "action_type": "ASK",
                        "place_name": target_unscheduled["name"],
                        "visit_date": None,
                        "local_start_time": extracted_time,
                        "reply": (
                            f"Quel jour souhaitez-vous planifier la visite de « {target_unscheduled['name']} »"
                            + (f" à {extracted_time} ?" if extracted_time else " ?")
                        ),
                        "proposed_action": None,
                    }
                new_time = extracted_time or "14:00"
                sim_score = (
                    round(best_catalog_score, 3)
                    if explicit_catalog_place is not None
                    else 0.85
                )
                return {
                    "action_type": "MOVE_VISIT" if has_move_verb else "ADD_VISIT",
                    "place_name": target_unscheduled["name"],
                    "visit_date": named_date_str,
                    "local_start_time": new_time,
                    "place_similarity_score": sim_score,
                    "explicit_date": bool(named_date_str is not None),
                    "explicit_time": bool(extracted_time is not None),
                    "reply": (
                        f"Je vous propose d'ajouter « {target_unscheduled['name']} » le "
                        f"{_fmt_date_fr(named_date_str)} à {new_time} ({target_unscheduled.get('recommended_duration_min', 90)} min). "
                        "Rien n'est modifié tant que vous ne confirmez pas."
                    ),
                    "proposed_action": {
                        "action_type": "ADD_VISIT",
                        "item_id": None,
                        "place_id": target_unscheduled["id"],
                        "place_name": target_unscheduled["name"],
                        "visit_date": named_date_str,
                        "local_start_time": new_time,
                        "duration_minutes": int(target_unscheduled.get("recommended_duration_min", 90)),
                        "transit_mode": "METRO",
                        "place_similarity_score": sim_score,
                        "explicit_date": bool(named_date_str is not None),
                        "explicit_time": bool(extracted_time is not None),
                    },
                }

            # Ex: "on change un truc", "déplace une visite" ou lieu inconnu
            return _build_unrecognized_or_unknown_place_reply()

        # ---------------------------------------------------------------------
        # 3. INTENTION : AJOUTER / PLANIFIER UNE VISITE (ou "<Lieu> <Date> <Heure>" sans verbe)
        # ---------------------------------------------------------------------
        if (
            has_explicit_add_verb
            or has_put_or_go_verb
            or (explicit_catalog_place is not None and (named_date_str is not None or extracted_time is not None))
        ):
            target_place = explicit_catalog_place or (
                _find_pronoun_place_in_catalog() if has_pronoun_ref else None
            )
            if target_place is None:
                return _build_unrecognized_or_unknown_place_reply()

            existing_for_place = next(
                (it for it in reversed(itinerary_items) if str(it.get("place_id")) == str(target_place["id"])),
                None,
            )
            new_time = extracted_time or "14:00"
            has_strict_add_verb = bool(
                re.search(r"\b(ajoute|ajouter|ajoutes|ajoutez|rajoute|rajouter|rajoutes|rajoutez)\b", msg_lower)
            )
            wants_second_time = bool(
                re.search(r"(deuxi[èe]me\s+fois|seconde\s+fois|une\s+autre\s+fois|encore\s+une\s+fois)", msg_lower)
            )
            sim_score = (
                round(best_catalog_score, 3)
                if explicit_catalog_place is not None
                else 0.85
            )

            # Si ce lieu est déjà au programme et que l'utilisateur n'a pas demandé un ajout explicite ("ajoute"), ADD devient MOVE
            if existing_for_place is not None and not has_strict_add_verb and not wants_second_time:
                move_date = named_date_str if named_date_str else existing_for_place["visit_date"]
                move_time = extracted_time if extracted_time else existing_for_place["local_start_time"]
                return {
                    "action_type": "MOVE_VISIT",
                    "place_name": target_place["name"],
                    "visit_date": move_date,
                    "local_start_time": move_time,
                    "place_similarity_score": sim_score,
                    "explicit_date": bool(named_date_str is not None),
                    "explicit_time": bool(extracted_time is not None),
                    "reply": (
                        f"Je vous propose de déplacer « {target_place['name']} » au "
                        f"{_fmt_date_fr(move_date)} à {move_time}. Souhaitez-vous appliquer ce changement ?"
                    ),
                    "proposed_action": {
                        "action_type": "MOVE_VISIT",
                        "item_id": existing_for_place["item_id"],
                        "place_id": target_place["id"],
                        "place_name": target_place["name"],
                        "visit_date": move_date,
                        "local_start_time": move_time,
                        "duration_minutes": int(existing_for_place.get("duration_minutes", 90)),
                        "transit_mode": existing_for_place.get("transit_mode", "METRO"),
                        "place_similarity_score": sim_score,
                        "explicit_date": bool(named_date_str is not None),
                        "explicit_time": bool(extracted_time is not None),
                    },
                }

            if named_date_str is None:
                return {
                    "action_type": "ASK",
                    "place_name": target_place["name"],
                    "visit_date": None,
                    "local_start_time": extracted_time,
                    "reply": (
                        f"Quel jour souhaitez-vous planifier la visite de « {target_place['name']} »"
                        + (f" à {extracted_time} ?" if extracted_time else " ?")
                    ),
                    "proposed_action": None,
                }

            return {
                "action_type": "ADD_VISIT",
                "place_name": target_place["name"],
                "visit_date": named_date_str,
                "local_start_time": new_time,
                "place_similarity_score": sim_score,
                "explicit_date": bool(named_date_str is not None),
                "explicit_time": bool(extracted_time is not None),
                "reply": (
                    f"Je vous propose d'ajouter « {target_place['name']} » le "
                    f"{_fmt_date_fr(named_date_str)} à {new_time} ({target_place.get('recommended_duration_min', 90)} min). "
                    "Rien n'est modifié tant que vous ne confirmez pas."
                ),
                "proposed_action": {
                    "action_type": "ADD_VISIT",
                    "item_id": None,
                    "place_id": target_place["id"],
                    "place_name": target_place["name"],
                    "visit_date": named_date_str,
                    "local_start_time": new_time,
                    "duration_minutes": int(target_place.get("recommended_duration_min", 90)),
                    "transit_mode": "METRO",
                    "place_similarity_score": sim_score,
                    "explicit_date": bool(named_date_str is not None),
                    "explicit_time": bool(extracted_time is not None),
                },
            }

        # ---------------------------------------------------------------------
        # 4. INCOMPRÉHENSION OU HÉSITATION : Question de clarification (jamais au hasard ni hors sujet)
        # ---------------------------------------------------------------------
        if explicit_catalog_place is not None:
            return {
                "action_type": "ASK",
                "place_name": explicit_catalog_place["name"],
                "visit_date": None,
                "local_start_time": None,
                "reply": (
                    f"Que souhaitez-vous faire avec « {explicit_catalog_place['name']} » ? "
                    "Voulez-vous ajouter, déplacer ou retirer cette visite (et à quel jour / quelle heure) ?"
                ),
                "proposed_action": None,
            }

        return _build_unrecognized_or_unknown_place_reply()


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


def _normalize_voice_stt_signal(
    *,
    provider_id: str,
    provider_label_fr: str,
    transits_browser_service: bool,
    privacy_notice_fr: str,
    transcript_text: str | None = None,
    audio_base64: str | None = None,
    signal: str = "SPEECH",
    confidence: float = 0.95,
) -> dict[str, Any]:
    sig = (signal or "SPEECH").strip().upper()
    cleaned_text = (transcript_text or "").strip()

    if sig == "MIC_DENIED":
        return {
            "ok": False,
            "signal": "MIC_DENIED",
            "error_code": "MIC_DENIED",
            "transcript": "",
            "confidence": 0.0,
            "language": "fr-FR",
            "provider_id": provider_id,
            "provider_label_fr": provider_label_fr,
            "transits_browser_service": transits_browser_service,
            "privacy_notice_fr": privacy_notice_fr,
            "message_fr": (
                "Accès au microphone refusé. Veuillez autoriser le microphone dans les paramètres "
                "du navigateur ou saisir votre demande au clavier. Aucune modification n'a été appliquée."
            ),
        }

    if sig == "BROWSER_UNSUPPORTED":
        return {
            "ok": False,
            "signal": "BROWSER_UNSUPPORTED",
            "error_code": "BROWSER_UNSUPPORTED",
            "transcript": "",
            "confidence": 0.0,
            "language": "fr-FR",
            "provider_id": provider_id,
            "provider_label_fr": provider_label_fr,
            "transits_browser_service": transits_browser_service,
            "privacy_notice_fr": privacy_notice_fr,
            "message_fr": (
                "Navigateur non compatible avec la Web Speech API (fr-FR). "
                "Vous pouvez basculer sur le fournisseur Whisper local dans les Paramètres ou utiliser le clavier."
            ),
        }

    if sig == "NOISE":
        return {
            "ok": False,
            "signal": "NOISE",
            "error_code": "NOISE",
            "transcript": "",
            "confidence": 0.0,
            "language": "fr-FR",
            "provider_id": provider_id,
            "provider_label_fr": provider_label_fr,
            "transits_browser_service": transits_browser_service,
            "privacy_notice_fr": privacy_notice_fr,
            "message_fr": (
                "Bruit ambiant trop élevé détecté. Pouvez-vous répéter ? "
                "Aucune modification n'a été effectuée."
            ),
        }

    if sig == "SILENCE":
        return {
            "ok": False,
            "signal": "SILENCE",
            "error_code": "SILENCE",
            "transcript": "",
            "confidence": 0.0,
            "language": "fr-FR",
            "provider_id": provider_id,
            "provider_label_fr": provider_label_fr,
            "transits_browser_service": transits_browser_service,
            "privacy_notice_fr": privacy_notice_fr,
            "message_fr": "Silence détecté : écoute arrêtée sans aucune modification.",
        }

    if confidence < 0.60 and sig == "SPEECH":
        return {
            "ok": False,
            "signal": "UNRECOGNIZED_SPEECH",
            "error_code": "LOW_CONFIDENCE",
            "transcript": cleaned_text,
            "confidence": float(confidence),
            "language": "fr-FR",
            "provider_id": provider_id,
            "provider_label_fr": provider_label_fr,
            "transits_browser_service": transits_browser_service,
            "privacy_notice_fr": privacy_notice_fr,
            "message_fr": "Pouvez-vous répéter ? La confiance de transcription vocale est trop faible, aucune action n'a été exécutée.",
        }

    if sig == "UNRECOGNIZED_SPEECH" or confidence < 0.60 or (not cleaned_text and not audio_base64):
        return {
            "ok": False,
            "signal": "UNRECOGNIZED_SPEECH",
            "error_code": "UNRECOGNIZED_SPEECH",
            "transcript": cleaned_text,
            "confidence": float(confidence),
            "language": "fr-FR",
            "provider_id": provider_id,
            "provider_label_fr": provider_label_fr,
            "transits_browser_service": transits_browser_service,
            "privacy_notice_fr": privacy_notice_fr,
            "message_fr": "Pouvez-vous répéter ? Je n'ai pas compris votre parole.",
        }

    return {
        "ok": True,
        "signal": "SPEECH",
        "error_code": None,
        "transcript": cleaned_text,
        "confidence": float(confidence),
        "language": "fr-FR",
        "provider_id": provider_id,
        "provider_label_fr": provider_label_fr,
        "transits_browser_service": transits_browser_service,
        "privacy_notice_fr": privacy_notice_fr,
        "message_fr": f"Transcription vocale ({provider_label_fr}) : « {cleaned_text} ».",
    }


class WebSpeechSTTProvider(BaseVoiceSTTProvider):
    """Adaptateur Web Speech API (fr-FR, côté navigateur)."""

    provider_id = "web_speech"
    provider_label_fr = "Web Speech API (navigateur, fr-FR)"
    language = "fr-FR"
    transits_browser_service = True
    privacy_notice_fr = (
        "Confidentialité vocale : en utilisant la Web Speech API, l'audio peut transiter "
        "par le service de reconnaissance du navigateur."
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    async def transcribe(
        self,
        *,
        transcript_text: str | None = None,
        audio_base64: str | None = None,
        signal: str = "SPEECH",
        confidence: float = 0.95,
    ) -> dict[str, Any]:
        return _normalize_voice_stt_signal(
            provider_id=self.provider_id,
            provider_label_fr=self.provider_label_fr,
            transits_browser_service=self.transits_browser_service,
            privacy_notice_fr=self.privacy_notice_fr,
            transcript_text=transcript_text,
            audio_base64=audio_base64,
            signal=signal,
            confidence=confidence,
        )


class LocalWhisperSTTProvider(BaseVoiceSTTProvider):
    """
    Adaptateur Whisper local (fr-FR) derrière la même interface BaseVoiceSTTProvider.
    Permet de remplacer la Web Speech API du navigateur sans modifier l'analyseur ni les écrans.
    """

    provider_id = "whisper_local"
    provider_label_fr = "Whisper local (fr-FR, traitement local)"
    language = "fr-FR"
    transits_browser_service = False
    privacy_notice_fr = (
        "Confidentialité vocale : avec Whisper local, l'audio est transcrit localement "
        "sans transiter par le service de reconnaissance du navigateur."
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings
        self.model_name = settings.WHISPER_LOCAL_MODEL if settings else "whisper-small-fr"

    async def transcribe(
        self,
        *,
        transcript_text: str | None = None,
        audio_base64: str | None = None,
        signal: str = "SPEECH",
        confidence: float = 0.96,
    ) -> dict[str, Any]:
        res = _normalize_voice_stt_signal(
            provider_id=self.provider_id,
            provider_label_fr=self.provider_label_fr,
            transits_browser_service=self.transits_browser_service,
            privacy_notice_fr=self.privacy_notice_fr,
            transcript_text=transcript_text,
            audio_base64=audio_base64,
            signal=signal,
            confidence=confidence,
        )
        res["whisper_model"] = self.model_name
        return res


def get_voice_stt_provider(
    provider_mode: str | None = None,
    settings: Settings | None = None,
) -> BaseVoiceSTTProvider:
    mode = (provider_mode or (settings.VOICE_STT_PROVIDER_MODE if settings else "web_speech")).strip().lower()
    if mode in {"whisper", "whisper_local", "local_whisper"}:
        return LocalWhisperSTTProvider(settings=settings)
    return WebSpeechSTTProvider(settings=settings)

