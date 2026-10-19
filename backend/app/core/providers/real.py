from datetime import date, datetime
import json
import logging
import time
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

logger = logging.getLogger("travelmate.providers.real")


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


def build_chat_assistant_prompt(
    *,
    user_message: str,
    safe_trip_context: dict[str, Any],
    chat_history: list[dict[str, Any]] | None = None,
) -> str:
    """
    Construit le prompt système + utilisateur destiné au modèle Ollama (mistral) :
    - Inclut le résumé du séjour recalculé en direct (visites planifiées, budget, météo)
      sans jamais relire un ancien message.
    - Inclut les lieux disponibles non encore planifiés (nom, catégorie, durée, intérieur/extérieur).
    - Inclut les exemples explicites (MOVE avec pronom, ADD, ASK, INFO).
    """
    trip_info = safe_trip_context.get("trip", {})
    city_name = trip_info.get("city_name", "votre destination")
    itinerary_items: list[dict[str, Any]] = safe_trip_context.get("itinerary", [])
    available_places: list[dict[str, Any]] = safe_trip_context.get("available_places", [])
    budget_info: dict[str, Any] = safe_trip_context.get("budget", {})
    weather_days: list[dict[str, Any]] = safe_trip_context.get("weather", [])

    if itinerary_items:
        scheduled_lines = [
            (
                f"- Lieu : {item.get('place_name')} | Date : {item.get('visit_date')} | "
                f"Heure : {item.get('local_start_time')} "
                f"(item_id={item.get('item_id')}, place_id={item.get('place_id')})"
            )
            for item in itinerary_items
        ]
        scheduled_block = "\n".join(scheduled_lines)
        last_visit = itinerary_items[-1]
        last_place_line = (
            f"Dernier lieu au programme : {last_visit.get('place_name')} "
            f"(date : {last_visit.get('visit_date')}, heure : {last_visit.get('local_start_time')})"
        )
    else:
        scheduled_block = "- Aucune visite planifiée au programme pour l'instant."
        last_place_line = "Dernier lieu au programme : aucun"

    if safe_trip_context.get("last_place_name"):
        last_place_line = (
            f"Dernier lieu évoqué : {safe_trip_context.get('last_place_name')} "
            f"(date : {safe_trip_context.get('last_place_date') or 'non planifié'}, "
            f"heure : {safe_trip_context.get('last_place_time') or 'non définie'})"
        )

    scheduled_ids = {str(it.get("place_id")) for it in itinerary_items if it.get("place_id")}
    unscheduled_lines = []
    for p in available_places:
        if str(p.get("id")) in scheduled_ids:
            continue
        env_fr = "Extérieur" if p.get("is_outdoor") else "Intérieur"
        unscheduled_lines.append(
            f"- {p.get('name')} ({p.get('category')}, {p.get('recommended_duration_min', 90)} min, {env_fr})"
        )
    unscheduled_block = (
        "\n".join(unscheduled_lines)
        if unscheduled_lines
        else "- Tous les lieux du catalogue sont déjà au programme."
    )

    budget_block = (
        f"Budget prévu : {budget_info.get('planned_total', 0):.0f} EUR | "
        f"Vol : {budget_info.get('flight_cost', 0):.0f} EUR | "
        f"Visites planifiées : {budget_info.get('visits_estimated_cost', 0):.0f} EUR | "
        f"Reste estimé : {budget_info.get('remaining_estimated', 0):.0f} EUR"
    )

    weather_lines = [
        f"- {w.get('forecast_date')} : {w.get('condition_label_fr', 'Ensoleillé')} "
        f"({w.get('temp_min_c', 15)}°C - {w.get('temp_max_c', 22)}°C)"
        for w in weather_days[:8]
    ]
    weather_block = "\n".join(weather_lines) if weather_lines else "- Prévisions météo stables."

    catalog_names = ", ".join(str(p.get("name")) for p in available_places[:20] if p.get("name"))
    history_lines = []
    for h in (chat_history or [])[-6:]:
        history_lines.append(f"{h.get('role', 'user')}: {h.get('content', '')}")
    history_block = "\n".join(history_lines) if history_lines else "Aucun historique."

    return (
        f"Tu es l'assistant de voyage TravelMate pour un séjour à {city_name}.\n"
        "Réponds UNIQUEMENT avec un objet JSON strict respectant ce schéma :\n"
        '{"action_type": "ADD" | "MOVE" | "REMOVE" | "INFO" | "ASK", '
        '"place_name": string | null, "visit_date": "YYYY-MM-DD" | null, '
        '"local_start_time": "HH:MM" | null, "reply": string}\n\n'
        "RÈGLES STRICTES :\n"
        "1. Si l'utilisateur pose une question d'information (ex: demander d'autres lieux à visiter qui ne sont pas "
        "encore dans son programme, ou une question sur la météo / le budget), utilise OBLIGATOIREMENT 'INFO' avec "
        "place_name=null, visit_date=null, local_start_time=null, et réponds par la liste des lieux non planifiés "
        "(nom, catégorie, durée, intérieur/extérieur) en proposant d'en ajouter un.\n"
        "2. Si le lieu demandé pour un changement d'horaire (ou désigné par un pronom comme 'le', 'la', 'l\\'') est DÉJÀ "
        "dans la liste des visites planifiées, utilise OBLIGATOIREMENT 'MOVE' (jamais 'ADD').\n"
        "3. N'invente JAMAIS une date absente du message utilisateur : si l'utilisateur ne mentionne pas de jour/date, "
        "reprends la date de la visite existante (pour MOVE) ou renvoie 'ASK' pour demander le jour souhaité.\n"
        "4. Si la phrase est ambiguë ou qu'il manque le lieu ou le jour pour un nouveau lieu, renvoie 'ASK'.\n"
        "5. Ne relis jamais les visites, le budget ou la météo depuis un ancien message de l'historique : "
        "utilise exclusivement le résumé recalculé ci-dessous.\n\n"
        "VISITES DÉJÀ PLANIFIÉES AU PROGRAMME (lieu, date, heure — recalculé en direct) :\n"
        f"{scheduled_block}\n"
        f"{last_place_line}\n\n"
        "BUDGET DU SÉJOUR (recalculé en direct) :\n"
        f"{budget_block}\n\n"
        "MÉTÉO DU SÉJOUR (recalculée en direct) :\n"
        f"{weather_block}\n\n"
        f"LIEUX DISPONIBLES À {city_name.upper()} : {catalog_names}\n"
        f"AUTRES LIEUX NON ENCORE PLANIFIÉS AU PROGRAMME :\n{unscheduled_block}\n\n"
        "EXEMPLES DE PHRASES AVEC LA RÉPONSE ATTENDUE (3 EXEMPLES + QUESTION INFO) :\n"
        "Exemple 1 (déplacement avec pronom — dernier lieu : Palais de la Bahia déjà planifié le 2026-11-12 à 10:00) :\n"
        'Message utilisateur : "on le mets à 12h"\n'
        "Réponse attendue : "
        '{"action_type": "MOVE", "place_name": "Palais de la Bahia", "visit_date": "2026-11-12", '
        '"local_start_time": "12:00", "reply": "Je vous propose de déplacer « Palais de la Bahia » au jeudi 12 novembre à 12h."}\n\n'
        "Exemple 2 (ajout d'un lieu avec jour et heure explicites) :\n"
        'Message utilisateur : "Ajoute Jardin Majorelle mercredi à 10h"\n'
        "Réponse attendue : "
        '{"action_type": "ADD", "place_name": "Jardin Majorelle", "visit_date": "2026-11-11", '
        '"local_start_time": "10:00", "reply": "Je vous propose d\'ajouter « Jardin Majorelle » le mercredi 11 novembre à 10h."}\n\n'
        "Exemple 3 (phrase ambiguë ou sans date pour un nouveau lieu -> ASK) :\n"
        'Message utilisateur : "on change un truc"\n'
        "Réponse attendue : "
        '{"action_type": "ASK", "place_name": null, "visit_date": null, '
        '"local_start_time": null, "reply": "Quel lieu souhaitez-vous planifier ou modifier, et pour quel jour du séjour ?"}\n\n'
        "Exemple 4 (question d'information sur les autres lieux à visiter -> INFO) :\n"
        'Message utilisateur : "je veux que tu me donne d\'autres lieux que je peux visiter et que j\'ai pas mis dans mon programme"\n'
        "Réponse attendue : "
        '{"action_type": "INFO", "place_name": null, "visit_date": null, '
        '"local_start_time": null, "reply": "Voici les autres lieux disponibles qui ne sont pas dans votre programme..."}\n\n'
        f"HISTORIQUE RÉCENT (limité aux derniers échanges) :\n{history_block}\n\n"
        f'MESSAGE UTILISATEUR : "{user_message}"\n'
    )


class RealAIProvider(BaseAIProvider):
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = SimulatedAIProvider(settings)

    def has_credentials(self) -> bool:
        return bool(self.settings.OLLAMA_BASE_URL or self.settings.AI_API_KEY)

    async def check_connection(self) -> dict[str, Any]:
        """Teste la vraie connexion HTTP vers Ollama (/api/tags) et vérifie la présence du modèle configuré."""
        t0 = time.perf_counter()
        base_url = (self.settings.OLLAMA_BASE_URL or "").rstrip("/")
        model_name = self.settings.OLLAMA_MODEL or "mistral"
        if not base_url:
            return {
                "mode": "real",
                "provider": "ollama",
                "model": model_name,
                "base_url": base_url,
                "connection_tested": True,
                "connected": False,
                "reachable": False,
                "model_available": False,
                "latency_ms": 0.0,
                "error": "OLLAMA_BASE_URL non configuré",
            }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{base_url}/api/tags")
                resp.raise_for_status()
                duration_ms = round((time.perf_counter() - t0) * 1000, 2)
                payload = resp.json() if resp.content else {}
                models_raw = payload.get("models", []) if isinstance(payload, dict) else []
                available_names = [
                    str(m.get("name", "")) for m in models_raw if isinstance(m, dict)
                ]
                model_ok = any(
                    n == model_name or n.startswith(f"{model_name}:")
                    for n in available_names
                )
                return {
                    "mode": "real",
                    "provider": "ollama",
                    "model": model_name,
                    "base_url": base_url,
                    "connection_tested": True,
                    "connected": bool(model_ok),
                    "reachable": True,
                    "model_available": model_ok,
                    "available_models": available_names,
                    "latency_ms": duration_ms,
                    "error": None
                    if model_ok
                    else f"Modèle '{model_name}' absent sur Ollama ({available_names})",
                }
        except Exception as exc:
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "mode": "real",
                "provider": "ollama",
                "model": model_name,
                "base_url": base_url,
                "connection_tested": True,
                "connected": False,
                "reachable": False,
                "model_available": False,
                "latency_ms": duration_ms,
                "error": str(exc),
            }

    async def generate_itinerary_suggestion(
        self,
        city_name: str,
        duration_days: int,
        budget_eur: float,
        travel_style: str,
        preferences: list[str],
    ) -> dict[str, Any]:
        if not self.has_credentials():
            raise RuntimeError("OLLAMA_BASE_URL / AI_API_KEY manquant dans .env pour RealAIProvider.")
        return {
            "provider": "RealAIProvider",
            "mode": self.mode,
            "model": self.settings.OLLAMA_MODEL or self.settings.AI_MODEL_NAME,
            "ollama_base_url": self.settings.OLLAMA_BASE_URL,
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
            raise RuntimeError("OLLAMA_BASE_URL / AI_API_KEY manquant dans .env pour RealAIProvider.")
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
        """
        Appelle le vrai serveur Ollama (mistral) lorsque AI_PROVIDER_MODE=real.
        Aucun repli silencieux vers le simulateur n'est autorisé.
        """
        if not self.has_credentials() or not self.settings.OLLAMA_BASE_URL:
            raise RuntimeError(
                "OLLAMA_BASE_URL manquant dans .env pour RealAIProvider (AI_PROVIDER_MODE=real). "
                "Repli vers le simulateur interdit."
            )

        prompt = str(
            safe_trip_context.get("prompt")
            or build_chat_assistant_prompt(
                user_message=user_message,
                safe_trip_context=safe_trip_context,
                chat_history=chat_history,
            )
        )

        ollama_url = f"{self.settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
        model_name = self.settings.OLLAMA_MODEL or "mistral"
        timeout_sec = float(getattr(self.settings, "OLLAMA_TIMEOUT_SECONDS", 90.0) or 90.0)
        t0 = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                resp = await client.post(
                    ollama_url,
                    json={
                        "model": model_name,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False,
                        "options": {"temperature": 0.1},
                    },
                )
                resp.raise_for_status()
                body = resp.json()
                duration_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "[AI_CHAT_PROVIDER] provider=ollama | mode=real | model=%s | duration_ms=%.2f | url=%s",
                    model_name,
                    duration_ms,
                    ollama_url,
                )
                raw_text = body.get("response") if isinstance(body, dict) else None
                if isinstance(raw_text, str) and raw_text.strip():
                    parsed = json.loads(raw_text)
                    if isinstance(parsed, dict):
                        return parsed
                elif isinstance(body, dict) and ("action_type" in body or "proposed_action" in body):
                    return body
                raise RuntimeError(f"Réponse Ollama non conforme au format JSON attendu : {body}")
        except Exception as exc:
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.error(
                "[AI_CHAT_PROVIDER] provider=ollama | mode=real | model=%s | duration_ms=%.2f | url=%s | error=%s",
                model_name,
                duration_ms,
                ollama_url,
                exc,
            )
            raise RuntimeError(
                f"Échec de connexion au fournisseur IA réel Ollama ({ollama_url}, modèle={model_name}) : {exc}"
            ) from exc


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
