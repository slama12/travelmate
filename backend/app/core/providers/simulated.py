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
        Assistant de voyage déterministe et sécurisé :
        - Exploite le programme, le vol, l'hébergement, le budget et la météo du voyage en cours.
        - Détecte les demandes d'ajout, déplacement ou suppression de visite et construit une
          proposition d'action qui devra être validée par le moteur ET confirmée par l'utilisateur.
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

        msg_lower = user_message.lower().strip()
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

            # 4. Date française "11 novembre", "10 juin"
            month_map = {
                "janvier": 1,
                "février": 2,
                "fevrier": 2,
                "mars": 3,
                "avril": 4,
                "mai": 5,
                "juin": 6,
                "juillet": 7,
                "août": 8,
                "aout": 8,
                "septembre": 9,
                "octobre": 10,
                "novembre": 11,
                "décembre": 12,
                "decembre": 12,
            }
            dm_m = re.search(
                r"\b(\d{1,2})\s+(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\b",
                lower,
            )
            if dm_m:
                day_num = int(dm_m.group(1))
                month_num = month_map[dm_m.group(2)]
                for d_obj in trip_date_objs:
                    if d_obj.day == day_num and d_obj.month == month_num:
                        return d_obj.isoformat()
                try:
                    return date(base_d.year, month_num, day_num).isoformat()
                except ValueError:
                    pass

            # 5. Nom de jour de la semaine ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
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
            if wd_matches:
                target_wd = weekday_map[wd_matches[-1]]
                for d_obj in trip_date_objs:
                    if d_obj.weekday() == target_wd:
                        return d_obj.isoformat()
                delta_days = (target_wd - base_d.weekday()) % 7
                return (base_d + timedelta(days=delta_days)).isoformat()

            return None

        named_date_str = _resolve_named_date(user_message)

        # Extraction d'une heure (HH:MM, HhMM ou Hh) hors dates ISO
        msg_without_iso = re.sub(r"\b20\d{2}-\d{2}-\d{2}\b", " ", msg_lower)
        time_match = re.search(r"\b(\d{1,2})\s*(?:h|:)\s*(\d{2})?\b", msg_without_iso)
        extracted_time: str | None = None
        if time_match:
            hh = int(time_match.group(1))
            mm = int(time_match.group(2) or "0")
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                extracted_time = f"{hh:02d}:{mm:02d}"

        default_date_str = (
            named_date_str
            if named_date_str
            else (
                itinerary_items[0]["visit_date"]
                if itinerary_items
                else trip_dates_iso[0]
            )
        )

        # Recherche d'un lieu explicitement mentionné dans le message
        def _find_explicit_scheduled_item() -> dict[str, Any] | None:
            for item in itinerary_items:
                p_name = str(item.get("place_name", "")).lower()
                tokens = [tok for tok in re.split(r"\W+", p_name) if len(tok) >= 4]
                if p_name and (p_name in msg_lower or any(t in msg_lower for t in tokens)):
                    return item
            return None

        def _find_scheduled_item() -> dict[str, Any] | None:
            explicit = _find_explicit_scheduled_item()
            if explicit:
                return explicit
            last_pid = safe_trip_context.get("last_place_id")
            if last_pid:
                for item in reversed(itinerary_items):
                    if item.get("place_id") == last_pid:
                        return item
            return itinerary_items[-1] if itinerary_items else None

        def _find_explicit_place_in_catalog() -> dict[str, Any] | None:
            for p in available_places:
                p_name = str(p.get("name", "")).lower()
                tokens = [tok for tok in re.split(r"\W+", p_name) if len(tok) >= 4]
                if p_name and (p_name in msg_lower or any(t in msg_lower for t in tokens)):
                    return p
            return None

        def _find_place_in_catalog() -> dict[str, Any] | None:
            explicit = _find_explicit_place_in_catalog()
            if explicit:
                return explicit
            last_pid = safe_trip_context.get("last_place_id")
            if last_pid:
                for p in available_places:
                    if p.get("id") == last_pid:
                        return p
            scheduled_ids = {i.get("place_id") for i in itinerary_items}
            for p in available_places:
                if p.get("id") not in scheduled_ids:
                    return p
            return available_places[0] if available_places else None

        has_pronoun_ref = bool(
            re.search(
                r"\b(on\s+le\s+met|on\s+le\s+mets|on\s+la\s+met|on\s+la\s+mets|mets[- ]le|mets[- ]la|met[- ]le|met[- ]la|d[ée]cale[- ]le|d[ée]cale[- ]la|d[ée]place[- ]le|d[ée]place[- ]la)\b",
                msg_lower,
            )
        )
        has_explicit_add_verb = bool(
            re.search(r"\b(ajoute|ajouter|rajoute|rajouter)\b", msg_lower)
        ) and not any(
            kw in msg_lower for kw in ("déplace", "deplace", "déplacer", "deplacer", "décale", "decale")
        )

        # 0. Intention : Question d'information sur les autres lieux à visiter (Action INFO obligatoire)
        is_places_info_question = bool(
            re.search(
                r"(autres?\s+lieux?|pas\s+(encore\s+)?(mis|ajout[ée]|planifi[ée]|pr[ée]vu)?\s*(dans|au)\s+(mon\s+|le\s+)?programme|"
                r"(quels?|quelles?)\s+(sont\s+les\s+)?(lieux|visites|activit[ée]s|endroits|monuments|mus[ée]es|restaurants)|"
                r"(que|quoi)\s+(puis[- ]je|je\s+peux|peut[- ]on|on\s+peut)?\s*(visiter|voir|faire)|"
                r"(donne|donner|montre|montrer|liste|lister|sugg[èe]re|conseille|recommande)\b.*\b(lieux|visites|endroits|id[ée]es|activit[ée]s)|"
                r"\bid[ée]es?\s+de\s+(visites?|lieux|sorties?)\b)",
                msg_lower,
            )
        )
        if is_places_info_question:
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
                "place_name": None,
                "visit_date": None,
                "local_start_time": None,
                "reply": reply_txt,
                "proposed_action": None,
            }

        # 1. Intention : Supprimer / retirer une visite
        if any(kw in msg_lower for kw in ("retire", "retirer", "supprime", "supprimer", "enlève", "enlever", "annule")):
            target_item = _find_scheduled_item()
            if target_item:
                return {
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
                    },
                }

        # 2. Intention : Déplacer / décaler une visite (ou pronom sur une visite déjà au programme, hors verbe d'ajout explicite)
        explicit_sched = _find_explicit_scheduled_item()
        if not has_explicit_add_verb and (
            any(kw in msg_lower for kw in ("déplace", "deplace", "déplacer", "deplacer", "décale", "decale", "change l'heure"))
            or (has_pronoun_ref and itinerary_items)
            or (explicit_sched is not None and extracted_time is not None)
        ):
            target_item = explicit_sched or _find_scheduled_item()
            if target_item:
                new_date = named_date_str if named_date_str else target_item["visit_date"]
                new_time = extracted_time or "15:00"
                return {
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
                    },
                }

        # 3. Intention : Ajouter / planifier une visite (ou lorsqu'un jour est explicitement nommé hors question météo/budget)
        is_info_only = any(kw in msg_lower for kw in ("météo", "meteo", "budget", "quel temps"))
        if (
            any(
                kw in msg_lower
                for kw in (
                    "ajoute",
                    "ajouter",
                    "rajoute",
                    "rajouter",
                    "planifie",
                    "planifier",
                    "insère",
                    "insere",
                    "visiter",
                    "visite",
                    "aller",
                    "mets",
                    "mettre",
                    "programme",
                    "programmer",
                    "propose",
                )
            )
            or (named_date_str is not None and not is_info_only)
        ):
            target_place = _find_place_in_catalog()
            if target_place:
                existing_for_place = next(
                    (it for it in reversed(itinerary_items) if it.get("place_id") == target_place["id"]),
                    None,
                )
                new_time = extracted_time or "14:00"
                # Si ce lieu est déjà au programme et que l'utilisateur n'a pas demandé un ajout explicite, ADD devient MOVE
                if existing_for_place is not None and not has_explicit_add_verb:
                    move_date = named_date_str if named_date_str else existing_for_place["visit_date"]
                    return {
                        "reply": (
                            f"Je vous propose de déplacer « {target_place['name']} » au "
                            f"{_fmt_date_fr(move_date)} à {new_time}. Souhaitez-vous appliquer ce changement ?"
                        ),
                        "proposed_action": {
                            "action_type": "MOVE_VISIT",
                            "item_id": existing_for_place["item_id"],
                            "place_id": target_place["id"],
                            "place_name": target_place["name"],
                            "visit_date": move_date,
                            "local_start_time": new_time,
                            "duration_minutes": int(existing_for_place.get("duration_minutes", 90)),
                            "transit_mode": existing_for_place.get("transit_mode", "METRO"),
                        },
                    }
                effective_add_date = named_date_str or (
                    existing_for_place["visit_date"] if existing_for_place is not None else None
                )
                if effective_add_date is None:
                    return {
                        "reply": (
                            f"Quel jour souhaitez-vous planifier la visite de « {target_place['name']} » "
                            f"à {new_time} ?"
                        ),
                        "proposed_action": None,
                    }
                return {
                    "reply": (
                        f"Je vous propose d'ajouter « {target_place['name']} » le "
                        f"{_fmt_date_fr(effective_add_date)} à {new_time} ({target_place['recommended_duration_min']} min). "
                        "Rien n'est modifié tant que vous ne confirmez pas."
                    ),
                    "proposed_action": {
                        "action_type": "ADD_VISIT",
                        "item_id": None,
                        "place_id": target_place["id"],
                        "place_name": target_place["name"],
                        "visit_date": effective_add_date,
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
            f"{weather_list[0].get('condition_label_fr') or weather_list[0].get('summary', 'Ensoleillé')} "
            f"({weather_list[0].get('temp_max_c') or weather_list[0].get('temperature_celsius', 20)}°C)"
            if weather_list
            else "Prévision non disponible"
        )
        return {
            "action_type": "INFO",
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
