from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
import json
import logging
import re
import time
from typing import Any
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.database import AsyncSession, get_db
from app.core.geo import normalize_transit_mode
from app.core.itinerary_validator import (
    ItineraryValidationEngine,
    ScheduledVisitSnapshot,
    ValidationResult,
    ensure_utc,
    parse_local_slot_to_utc,
    to_destination_local,
)
from app.core.providers import (
    RealAIProvider,
    SimulatedAIProvider,
    build_chat_assistant_prompt,
    get_provider_registry,
)
from app.core.redis import cache_client
from app.models.entities import (
    Accommodation,
    ChatMessage,
    ChatUnrecognized,
    Destination,
    FlightBooking,
    ItineraryItem,
    Place,
    Trip,
    User,
)
from app.modules.auth.router import get_current_user
from app.modules.intelligence.schemas import (
    AcceptWeatherAlertRequest,
    AIApplyDraftRequest,
    AIDraftSlotSchema,
    AIGenerateItineraryDraftResponse,
    AIGenerateItineraryRequest,
    AIModelRawPlanSchema,
    ChatActionDecisionResponse,
    ChatConversationResponse,
    ChatMessageResponse,
    ChatProposedActionSchema,
    ChatSendMessageRequest,
    DailyWeatherForecastSchema,
    TripWeatherResponse,
    WeatherAdaptationOptionSchema,
    WeatherVisitAlertSchema,
)
from app.modules.itinerary.router import (
    _build_snapshots,
    _load_trip_items_with_places,
    _recompute_trip_day_transits,
    _sync_item_with_google_calendar,
    _to_item_response,
    get_trip_itinerary,
)
from app.modules.itinerary.schemas import (
    ItineraryItemResponse,
    SuggestedSlotSchema,
    TripItineraryScheduleResponse,
)

logger = logging.getLogger("travelmate.intelligence.chat")

router = APIRouter(prefix="/itinerary", tags=["Intelligence Étape 4 (Météo, IA, Chat, Trajets)"])


def _validate_slot(
    *,
    requested_start_utc: datetime,
    duration_minutes: int,
    destination_timezone: str,
    place_id: str,
    place_name: str,
    place_latitude: float,
    place_longitude: float,
    place_opening_hours: dict[str, Any] | None,
    trip_arrival_utc: datetime | None,
    trip_departure_utc: datetime | None,
    existing_items: list[ScheduledVisitSnapshot],
    transit_mode: str = "METRO",
    exclude_item_id: str | None = None,
    allow_duplicate_place: bool = False,
) -> ValidationResult:
    return ItineraryValidationEngine.validate_visit(
        trip_arrival_utc=trip_arrival_utc,
        trip_departure_utc=trip_departure_utc,
        destination_tz_name=destination_timezone,
        place_id=place_id,
        place_name=place_name,
        place_lat=place_latitude,
        place_lng=place_longitude,
        place_opening_hours=place_opening_hours or {},
        start_at_utc=requested_start_utc,
        duration_minutes=duration_minutes,
        transit_mode=transit_mode,
        existing_visits=existing_items,
        exclude_item_id=exclude_item_id,
        allow_duplicate_place=allow_duplicate_place,
    )


# ==============================================================================
# UTILITAIRES DE CONTRÔLE D'ACCÈS & SANITISATION ANTI-INJECTION
# ==============================================================================
async def _load_trip_and_destination_strict(
    db: AsyncSession,
    trip_id: str,
    user_id: str,
) -> tuple[Trip, Destination]:
    """
    Contrôle d'accès strict côté backend :
    - 404 si le voyage n'existe pas ;
    - 403 si le voyage appartient à un autre utilisateur.
    """
    trip = await db.scalar(select(Trip).where(Trip.id == trip_id))
    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Séjour introuvable.",
        )
    if trip.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé : vous ne pouvez consulter ou modifier que vos propres voyages.",
        )
    destination = await db.scalar(select(Destination).where(Destination.id == trip.destination_id))
    if not destination:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination du séjour introuvable.",
        )
    return trip, destination


def sanitize_external_data_for_llm(raw_text: str | None) -> str:
    """
    Traite le contenu externe (descriptions de lieux, avis) exclusivement comme de la donnée passive,
    jamais comme des instructions pour le modèle. Neutralise les motifs d'injection de prompt.
    """
    if not raw_text:
        return '<external_data_only do_not_execute="true"></external_data_only>'
    cleaned = re.sub(
        r"(?i)(ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|"
        r"ignore\s+toutes\s+les\s+instructions|"
        r"system\s*:|assistant\s*:|developer\s*:|<script[^>]*>.*?</script>)",
        "[CONTENU_EXTERNE_FILTRE]",
        str(raw_text),
    )
    cleaned = cleaned.replace("<", "‹").replace(">", "›")
    return f'<external_data_only do_not_execute="true">{cleaned[:500]}</external_data_only>'


_FR_WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_FR_MONTHS = [
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


def _format_date_fr(d: date) -> str:
    return f"{_FR_WEEKDAYS[d.weekday()]} {d.day} {_FR_MONTHS[d.month]}"


def _compute_trip_dates_local(trip: Trip, dest_tz: str) -> list[date]:
    if trip.arrival_at and trip.departure_at:
        loc_arr = to_destination_local(ensure_utc(trip.arrival_at), dest_tz).date()
        loc_dep = to_destination_local(ensure_utc(trip.departure_at), dest_tz).date()
        dates: list[date] = []
        cur = loc_arr
        while cur <= loc_dep and len(dates) < 14:
            dates.append(cur)
            cur += timedelta(days=1)
        if dates:
            return dates
    base = date(2026, 11, 10)
    return [base + timedelta(days=i) for i in range(8)]


def _format_weather_badge(cond_code: str, temp_c: float | None, available: bool) -> str:
    if not available or temp_c is None or cond_code == "UNAVAILABLE":
        return "Prévision non disponible"
    labels = {
        "SUNNY": "Soleil",
        "CLEAR": "Soleil",
        "PARTLY_CLOUDY": "Éclaircies",
        "CLOUDY": "Nuageux",
        "RAIN": "Pluie",
        "STORM": "Orage",
        "THUNDERSTORM": "Orage",
    }
    short = labels.get(cond_code.upper(), "Météo")
    return f"{short} · {round(temp_c)}°C"


async def _fetch_trip_weather_forecasts(
    *,
    destination: Destination,
    trip_dates: list[date],
    horizon_days: int | None = None,
    reference_today: date | None = None,
    bypass_cache: bool = False,
) -> tuple[list[DailyWeatherForecastSchema], bool, str, int]:
    """
    Récupère les prévisions météo journalières avec :
    - Cache Redis (cache_client),
    - Gestion stricte de l'horizon de prévision et de l'indisponibilité ("Prévision non disponible", sans rien inventer).
    """
    settings = get_settings()
    registry = get_provider_registry()
    effective_horizon = (
        horizon_days if horizon_days is not None else int(settings.WEATHER_FORECAST_HORIZON_DAYS)
    )
    ref_today = reference_today or date.today()
    start_d = trip_dates[0]
    days_count = len(trip_dates)

    all_beyond_horizon = all(
        abs((d - ref_today).days) > effective_horizon for d in trip_dates
    )
    if all_beyond_horizon:
        unavailable_days = [
            DailyWeatherForecastSchema(
                date=d.isoformat(),
                available=False,
                condition_code="UNAVAILABLE",
                summary="Prévision non disponible",
                precipitation_probability=None,
                is_rainy=False,
                temperature_celsius=None,
                badge_label="Prévision non disponible",
            )
            for d in trip_dates
        ]
        return unavailable_days, False, "none", effective_horizon

    cache_key = (
        f"weather:v1:{destination.id}:{start_d.isoformat()}:{days_count}:"
        f"{effective_horizon}:{registry.weather.mode}"
    )
    raw_forecasts: list[dict[str, Any]] | None = None
    cache_hit = False
    cache_backend = "redis"

    if not bypass_cache:
        cached = await cache_client.get_json(cache_key)
        if isinstance(cached, dict) and isinstance(cached.get("days"), list):
            raw_forecasts = cached["days"]
            cache_hit = True

    if raw_forecasts is None:
        try:
            fetched = await registry.weather.get_daily_forecast(
                city_name=destination.city_name,
                latitude=destination.latitude,
                longitude=destination.longitude,
                start_date=start_d,
                days=days_count,
            )
            if isinstance(fetched, list) and len(fetched) > 0:
                raw_forecasts = fetched
                cache_backend = await cache_client.set_json(
                    cache_key, {"days": raw_forecasts}, ttl_seconds=1800
                )
            else:
                raw_forecasts = []
        except Exception:
            raw_forecasts = []

    by_date_raw: dict[str, dict[str, Any]] = {}
    for entry in raw_forecasts or []:
        if isinstance(entry, dict) and entry.get("date"):
            by_date_raw[str(entry["date"])] = entry

    result_days: list[DailyWeatherForecastSchema] = []
    for d in trip_dates:
        d_iso = d.isoformat()
        delta_days = abs((d - ref_today).days)
        raw_item = by_date_raw.get(d_iso)

        if (
            delta_days > effective_horizon
            or not raw_item
            or raw_item.get("available") is False
            or raw_item.get("condition_code") == "UNAVAILABLE"
        ):
            result_days.append(
                DailyWeatherForecastSchema(
                    date=d_iso,
                    available=False,
                    condition_code="UNAVAILABLE",
                    summary="Prévision non disponible",
                    precipitation_probability=None,
                    is_rainy=False,
                    temperature_celsius=None,
                    badge_label="Prévision non disponible",
                )
            )
            continue

        cond = str(raw_item.get("condition_code", "SUNNY")).upper()
        temp_c = (
            float(raw_item["temperature_celsius"])
            if raw_item.get("temperature_celsius") is not None
            else None
        )
        rain_prob = (
            int(raw_item["precipitation_probability"])
            if raw_item.get("precipitation_probability") is not None
            else 0
        )
        is_rainy = (
            bool(raw_item.get("is_rainy", False))
            or cond in {"RAIN", "STORM", "THUNDERSTORM"}
            or rain_prob >= 60
        )
        summary = str(raw_item.get("summary") or "Prévision météo")
        result_days.append(
            DailyWeatherForecastSchema(
                date=d_iso,
                available=True,
                condition_code=cond,
                summary=summary,
                precipitation_probability=rain_prob,
                is_rainy=is_rainy,
                temperature_celsius=temp_c,
                badge_label=_format_weather_badge(cond, temp_c, True),
            )
        )

    return result_days, cache_hit, cache_backend, effective_horizon


# ==============================================================================
# 1. ENDPOINTS MÉTÉO & ADAPTATION EN UN CLIC
# ==============================================================================
@router.get("/trip/{trip_id}/weather", response_model=TripWeatherResponse)
async def get_trip_weather_and_alerts(
    trip_id: str,
    horizon_days: int | None = Query(default=None, ge=1, le=365),
    bypass_cache: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripWeatherResponse:
    registry = get_provider_registry()
    trip, destination = await _load_trip_and_destination_strict(db, trip_id, current_user.id)
    dest_tz = destination.timezone or "UTC"
    trip_dates = _compute_trip_dates_local(trip, dest_tz)

    days_forecast, cache_hit, cache_backend, effective_horizon = await _fetch_trip_weather_forecasts(
        destination=destination,
        trip_dates=trip_dates,
        horizon_days=horizon_days,
        bypass_cache=bypass_cache,
    )
    forecast_by_date = {f.date: f for f in days_forecast}

    items, places_map = await _load_trip_items_with_places(db, trip.id)
    all_snapshots = _build_snapshots(items, places_map)

    dest_places_res = await db.scalars(
        select(Place).where(Place.destination_id == destination.id).order_by(Place.avg_rating.desc())
    )
    dest_places = list(dest_places_res.all())
    indoor_places = [p for p in dest_places if not p.is_outdoor]

    alerts: list[WeatherVisitAlertSchema] = []
    for item in items:
        place = places_map.get(item.place_id)
        if not place:
            continue
        loc_start = to_destination_local(ensure_utc(item.start_at), dest_tz)
        loc_end = to_destination_local(ensure_utc(item.end_at), dest_tz)
        visit_date_str = loc_start.strftime("%Y-%m-%d")
        day_weather = forecast_by_date.get(visit_date_str)

        is_rainy_outdoor = bool(
            day_weather
            and day_weather.available
            and day_weather.is_rainy
            and place.is_outdoor
            and not getattr(item, "weather_dismissed", False)
        )
        item.weather_warning = is_rainy_outdoor

        if not is_rainy_outdoor or not day_weather:
            continue

        other_snapshots = [s for s in all_snapshots if s.item_id != item.id]
        scheduled_place_ids_that_day = {
            i.place_id
            for i in items
            if i.id != item.id
            and to_destination_local(ensure_utc(i.start_at), dest_tz).strftime("%Y-%m-%d") == visit_date_str
        }

        options: list[WeatherAdaptationOptionSchema] = []

        # Option A : Lieu en intérieur le même jour (validé par le moteur de validation)
        sorted_indoor = sorted(
            indoor_places,
            key=lambda p: (
                0 if p.id not in scheduled_place_ids_that_day else 1,
                0 if p.category == "CULTURE" else 1,
                -(p.avg_rating or 4.5),
            ),
        )
        for indoor_cand in sorted_indoor:
            cand_dur = indoor_cand.recommended_duration_min or item.duration_minutes
            cand_start_utc, cand_end_utc = parse_local_slot_to_utc(
                visit_date=loc_start.date(),
                local_start_time_str=loc_start.strftime("%H:%M"),
                duration_minutes=cand_dur,
                timezone_name=dest_tz,
            )
            val_res = _validate_slot(
                requested_start_utc=cand_start_utc,
                duration_minutes=cand_dur,
                destination_timezone=dest_tz,
                place_id=indoor_cand.id,
                place_name=indoor_cand.name,
                place_latitude=indoor_cand.latitude,
                place_longitude=indoor_cand.longitude,
                place_opening_hours=indoor_cand.opening_hours or {},
                trip_arrival_utc=ensure_utc(trip.arrival_at) if trip.arrival_at else None,
                trip_departure_utc=ensure_utc(trip.departure_at) if trip.departure_at else None,
                existing_items=other_snapshots,
                transit_mode=normalize_transit_mode(item.transit_mode_to_next),
                exclude_item_id=item.id,
            )
            chosen_start_utc = cand_start_utc
            chosen_end_utc = cand_end_utc
            if not val_res.valid:
                same_day_sug = next(
                    (s for s in val_res.suggested_slots if s.local_date == visit_date_str),
                    None,
                )
                if same_day_sug:
                    chosen_start_utc = ensure_utc(same_day_sug.start_at_utc)
                    chosen_end_utc = ensure_utc(same_day_sug.end_at_utc)
                else:
                    continue

            c_loc_s = to_destination_local(chosen_start_utc, dest_tz)
            c_loc_e = to_destination_local(chosen_end_utc, dest_tz)
            options.append(
                WeatherAdaptationOptionSchema(
                    option_id=f"indoor-{indoor_cand.id}",
                    suggestion_type="INDOOR_PLACE",
                    label_fr=(
                        f"Remplacer par « {indoor_cand.name} » (en intérieur) "
                        f"le {_format_date_fr(c_loc_s.date())} de {c_loc_s.strftime('%H:%M')} à {c_loc_e.strftime('%H:%M')}"
                    ),
                    replacement_place_id=indoor_cand.id,
                    replacement_place_name=indoor_cand.name,
                    replacement_place_category=indoor_cand.category,
                    is_outdoor=False,
                    visit_date=c_loc_s.date(),
                    local_start_time=c_loc_s.strftime("%H:%M"),
                    local_end_time=c_loc_e.strftime("%H:%M"),
                    start_at=chosen_start_utc,
                    end_at=chosen_end_utc,
                    duration_minutes=cand_dur,
                    validated_by_engine=True,
                )
            )
            break

        # Option B : Déplacer la visite extérieure vers un autre créneau (jour sec) validé par le moteur
        dry_days = [f for f in days_forecast if f.available and not f.is_rainy and f.date != visit_date_str]
        for dry_f in dry_days:
            dry_date = date.fromisoformat(dry_f.date)
            alt_start_utc, alt_end_utc = parse_local_slot_to_utc(
                visit_date=dry_date,
                local_start_time_str=loc_start.strftime("%H:%M"),
                duration_minutes=item.duration_minutes,
                timezone_name=dest_tz,
            )
            alt_val = _validate_slot(
                requested_start_utc=alt_start_utc,
                duration_minutes=item.duration_minutes,
                destination_timezone=dest_tz,
                place_id=place.id,
                place_name=place.name,
                place_latitude=place.latitude,
                place_longitude=place.longitude,
                place_opening_hours=place.opening_hours or {},
                trip_arrival_utc=ensure_utc(trip.arrival_at) if trip.arrival_at else None,
                trip_departure_utc=ensure_utc(trip.departure_at) if trip.departure_at else None,
                existing_items=other_snapshots,
                transit_mode=normalize_transit_mode(item.transit_mode_to_next),
                exclude_item_id=item.id,
            )
            chosen_alt_start = alt_start_utc
            chosen_alt_end = alt_end_utc
            if not alt_val.valid:
                if alt_val.suggested_slots:
                    sug0 = alt_val.suggested_slots[0]
                    chosen_alt_start = ensure_utc(sug0.start_at_utc)
                    chosen_alt_end = ensure_utc(sug0.end_at_utc)
                else:
                    continue

            a_loc_s = to_destination_local(chosen_alt_start, dest_tz)
            a_loc_e = to_destination_local(chosen_alt_end, dest_tz)
            options.append(
                WeatherAdaptationOptionSchema(
                    option_id=f"slot-{a_loc_s.strftime('%Y-%m-%d-%H%M')}",
                    suggestion_type="ALTERNATE_SLOT",
                    label_fr=(
                        f"Déplacer « {place.name} » au {_format_date_fr(a_loc_s.date())} "
                        f"de {a_loc_s.strftime('%H:%M')} à {a_loc_e.strftime('%H:%M')} ({dry_f.summary})"
                    ),
                    replacement_place_id=place.id,
                    replacement_place_name=place.name,
                    replacement_place_category=place.category,
                    is_outdoor=bool(place.is_outdoor),
                    visit_date=a_loc_s.date(),
                    local_start_time=a_loc_s.strftime("%H:%M"),
                    local_end_time=a_loc_e.strftime("%H:%M"),
                    start_at=chosen_alt_start,
                    end_at=chosen_alt_end,
                    duration_minutes=item.duration_minutes,
                    validated_by_engine=True,
                )
            )
            break

        weather_title_prefix = (
            "Orage prévu"
            if str(day_weather.condition_code).upper() in {"STORM", "THUNDERSTORM"}
            else "Pluie prévue"
        )
        alerts.append(
            WeatherVisitAlertSchema(
                item_id=item.id,
                place_id=place.id,
                place_name=place.name,
                visit_date=visit_date_str,
                local_start_time=loc_start.strftime("%H:%M"),
                local_end_time=loc_end.strftime("%H:%M"),
                weather_condition_code=day_weather.condition_code,
                weather_summary=day_weather.summary,
                precipitation_probability=day_weather.precipitation_probability,
                alert_message_fr=(
                    f"{weather_title_prefix} le {_format_date_fr(loc_start.date())} "
                    f"pendant votre visite « {place.name} »."
                ),
                options=options,
            )
        )

    return TripWeatherResponse(
        trip_id=trip.id,
        destination_city=destination.city_name,
        destination_timezone=dest_tz,
        provider_mode=registry.weather.mode,
        forecast_horizon_days=effective_horizon,
        cache_hit=cache_hit,
        cache_backend=cache_backend,
        persisted_changes=False,
        days=days_forecast,
        alerts=alerts,
    )


@router.post("/trip/{trip_id}/weather/alerts/{item_id}/accept", response_model=ItineraryItemResponse)
async def accept_weather_alert_suggestion(
    trip_id: str,
    item_id: str,
    payload: AcceptWeatherAlertRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ItineraryItemResponse:
    """
    Applique en un clic la suggestion météo choisie par l'utilisateur après re-validation stricte
    par le moteur de validation, puis synchronise Google Calendar.
    """
    trip, destination = await _load_trip_and_destination_strict(db, trip_id, current_user.id)
    dest_tz = destination.timezone or "UTC"

    item = await db.scalar(
        select(ItineraryItem).where(ItineraryItem.id == item_id, ItineraryItem.trip_id == trip.id)
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visite introuvable.")

    new_place = await db.scalar(
        select(Place).where(
            Place.id == payload.replacement_place_id,
            Place.destination_id == destination.id,
        )
    )
    if not new_place:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lieu de remplacement introuvable dans cette destination.",
        )

    existing_items, places_map = await _load_trip_items_with_places(db, trip.id)
    other_snapshots = [s for s in _build_snapshots(existing_items, places_map) if s.item_id != item.id]

    requested_start_utc, requested_end_utc = parse_local_slot_to_utc(
        visit_date=payload.visit_date,
        local_start_time_str=payload.local_start_time,
        duration_minutes=payload.duration_minutes,
        timezone_name=dest_tz,
    )
    validation = _validate_slot(
        requested_start_utc=requested_start_utc,
        duration_minutes=payload.duration_minutes,
        destination_timezone=dest_tz,
        place_id=new_place.id,
        place_name=new_place.name,
        place_latitude=new_place.latitude,
        place_longitude=new_place.longitude,
        place_opening_hours=new_place.opening_hours or {},
        trip_arrival_utc=ensure_utc(trip.arrival_at) if trip.arrival_at else None,
        trip_departure_utc=ensure_utc(trip.departure_at) if trip.departure_at else None,
        existing_items=other_snapshots,
        transit_mode=normalize_transit_mode(payload.transit_mode),
        exclude_item_id=item.id,
    )
    if not validation.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": validation.reason_code,
                "message": validation.message,
                "suggested_slots": [
                    SuggestedSlotSchema(**s.to_dict()).model_dump(mode="json")
                    for s in validation.suggested_slots
                ],
            },
        )

    item.place_id = new_place.id
    item.visit_date = payload.visit_date
    item.start_at = requested_start_utc
    item.end_at = requested_end_utc
    item.duration_minutes = payload.duration_minutes
    item.transit_mode_to_next = normalize_transit_mode(payload.transit_mode)
    item.weather_warning = False
    item.weather_dismissed = False
    await db.commit()

    await _recompute_trip_day_transits(db, trip.id, dest_tz)
    await _sync_item_with_google_calendar(db, item, new_place, dest_tz, action="update")
    return _to_item_response(item, new_place, dest_tz)


@router.post("/trip/{trip_id}/weather/alerts/{item_id}/reject", response_model=ItineraryItemResponse)
async def reject_weather_alert_suggestion(
    trip_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ItineraryItemResponse:
    """
    L'utilisateur refuse la suggestion météo : la visite reste inchangée et l'alerte est masquée.
    """
    trip, destination = await _load_trip_and_destination_strict(db, trip_id, current_user.id)
    dest_tz = destination.timezone or "UTC"

    item = await db.scalar(
        select(ItineraryItem).where(ItineraryItem.id == item_id, ItineraryItem.trip_id == trip.id)
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visite introuvable.")

    place = await db.scalar(select(Place).where(Place.id == item.place_id))
    if not place:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lieu introuvable.")

    item.weather_dismissed = True
    item.weather_warning = False
    await db.commit()
    await db.refresh(item)
    return _to_item_response(item, place, dest_tz)


# ==============================================================================
# 2. ENDPOINTS ITINÉRAIRE IA ("GÉNÈRE MON PROGRAMME") — BROUILLON NON PERSISTÉ
# ==============================================================================
def _place_noun_fr(place: Place) -> str:
    cat = str(place.category or "").upper()
    name_low = str(place.name or "").lower()
    if cat == "RESTAURANT":
        return "le restaurant"
    if any(k in name_low for k in ("musée", "musee", "museum", "teamlab", "galerie")):
        return "le musée"
    if any(k in name_low for k in ("jardin", "parc", "park")):
        return "le jardin"
    return "le lieu"


def _extract_opening_start_hm(place: Place, target_start_hm: str) -> str:
    oh = place.opening_hours or {}
    raw_str = str(oh.get("daily") or next(iter(oh.values()), "09:00-18:00"))
    if raw_str.strip() == "24/7":
        return "00:00"
    starts: list[str] = []
    for part in raw_str.split(","):
        part = part.strip()
        if "-" in part:
            s_hm = part.split("-")[0].strip()
            starts.append(s_hm)
    if target_start_hm in starts:
        return target_start_hm
    return starts[0] if starts else target_start_hm


def _format_simple_slot_correction_fr(
    place: Place,
    val_res: ValidationResult,
    sug_date: date,
    sug_start_hm: str,
    orig_date: date,
) -> str:
    same_day = sug_date == orig_date
    prefix = (
        f"Déplacé à {sug_start_hm}"
        if same_day
        else f"Déplacé au {_format_date_fr(sug_date)} à {sug_start_hm}"
    )
    if val_res.reason_code == "OUTSIDE_OPENING_HOURS":
        open_hm = _extract_opening_start_hm(place, sug_start_hm)
        noun = _place_noun_fr(place)
        return f"{prefix} car {noun} ouvre à {open_hm}"
    if val_res.reason_code == "OUTSIDE_TRIP_WINDOW":
        phase = str((val_res.conflict_details or {}).get("violation_phase", ""))
        if phase in {"DEPARTURE_BUFFER", "AFTER_DEPARTURE"}:
            return f"{prefix} pour tenir compte du départ du vol retour"
        return f"{prefix} pour tenir compte de l'arrivée du vol"
    if val_res.reason_code == "OVERLAPPING_VISIT":
        return f"{prefix} car un autre lieu est déjà prévu sur ce créneau"
    return f"{prefix} pour laisser le temps de trajet"


@router.post("/trip/{trip_id}/ai-generate", response_model=AIGenerateItineraryDraftResponse)
async def generate_ai_itinerary_draft(
    trip_id: str,
    payload: AIGenerateItineraryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AIGenerateItineraryDraftResponse:
    """
    Génère un brouillon de programme par IA (non enregistré en base et non synchronisé à Google Calendar) :
    - 3 champs de formulaire (budget, rythme, goûts <= 4 champs),
    - JSON validé par Pydantic avec 2 tentatives maximum,
    - Filtre strictement les lieux existants en base pour la destination, sans doublon de lieu,
    - Ne propose jamais un lieu en plein air un jour d'orage ou de pluie (sauf demande explicite),
    - Corrige ou retire les créneaux invalides avec une phrase simple en français sans jargon,
    - Intègre la météo et l'optimisation des temps de trajet.
    """
    registry = get_provider_registry()
    trip, destination = await _load_trip_and_destination_strict(db, trip_id, current_user.id)
    dest_tz = destination.timezone or "UTC"
    trip_dates = _compute_trip_dates_local(trip, dest_tz)

    places_res = await db.scalars(
        select(Place).where(Place.destination_id == destination.id).order_by(Place.avg_rating.desc())
    )
    db_places = list(places_res.all())
    if not db_places:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Aucun lieu disponible en base pour cette destination.",
        )
    places_by_id: dict[str, Place] = {p.id: p for p in db_places}
    available_places_dicts = [
        {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "is_outdoor": bool(p.is_outdoor),
            "latitude": p.latitude,
            "longitude": p.longitude,
            "recommended_duration_min": p.recommended_duration_min,
            "estimated_cost": float(p.estimated_cost or 0.0),
            "price_tier": p.price_tier,
            "avg_rating": p.avg_rating,
            "opening_hours": p.opening_hours or {},
        }
        for p in db_places
    ]

    weather_days, _, _, _ = await _fetch_trip_weather_forecasts(
        destination=destination,
        trip_dates=trip_dates,
    )
    weather_by_date = {w.date: w.model_dump() for w in weather_days}

    def _is_rain_or_storm_date(d_iso: str) -> bool:
        w = weather_by_date.get(d_iso, {})
        if not w or not w.get("available", True):
            return False
        cond = str(w.get("condition_code", "")).upper()
        return bool(w.get("is_rainy", False)) or cond in {"RAIN", "STORM", "THUNDERSTORM"}

    max_attempts = 2
    parsed_plan: AIModelRawPlanSchema | None = None
    last_validation_error: str | None = None
    attempts_used = 0

    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        try:
            try:
                raw_output = await registry.ai.generate_structured_itinerary_raw(
                    city_name=destination.city_name,
                    trip_dates=trip_dates,
                    budget_eur=payload.budget_eur,
                    pace=payload.pace,
                    tastes=payload.tastes,
                    available_places=available_places_dicts,
                    weather_by_date=weather_by_date,
                    attempt=attempt,
                    allow_outdoor_in_rain=payload.allow_outdoor_in_rain,
                )
            except TypeError:
                raw_output = await registry.ai.generate_structured_itinerary_raw(
                    city_name=destination.city_name,
                    trip_dates=trip_dates,
                    budget_eur=payload.budget_eur,
                    pace=payload.pace,
                    tastes=payload.tastes,
                    available_places=available_places_dicts,
                    weather_by_date=weather_by_date,
                    attempt=attempt,
                )
            if isinstance(raw_output, str):
                parsed_plan = AIModelRawPlanSchema.model_validate_json(raw_output)
            elif isinstance(raw_output, dict):
                parsed_plan = AIModelRawPlanSchema.model_validate(raw_output)
            else:
                raise ValueError("Format de réponse IA non reconnu (attendu JSON str ou dict).")
            break
        except (ValidationError, json.JSONDecodeError, ValueError, Exception) as exc:
            last_validation_error = str(exc)
            parsed_plan = None

    if parsed_plan is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "AI_INVALID_JSON_AFTER_RETRIES",
                "attempts": attempts_used,
                "message": (
                    "La génération automatique du programme a échoué après 2 tentatives "
                    "(réponse du modèle invalide). Veuillez réessayer."
                ),
                "last_error": last_validation_error,
            },
        )

    adjustments_fr: list[str] = []
    draft_snapshots: list[ScheduledVisitSnapshot] = []
    accepted_slots: list[dict[str, Any]] = []
    used_place_ids: set[str] = set()

    trip_arr_utc = ensure_utc(trip.arrival_at) if trip.arrival_at else None
    trip_dep_utc = ensure_utc(trip.departure_at) if trip.departure_at else None

    for idx, raw_slot in enumerate(parsed_plan.slots):
        place = places_by_id.get(raw_slot.place_id)
        if place is None:
            adjustments_fr.append(
                f"Lieu inexistant en base (« {raw_slot.place_name or raw_slot.place_id} ») ignoré et retiré."
            )
            continue

        # Règle anti-doublon : ne jamais répéter un même lieu plus d'une fois
        if place.id in used_place_ids:
            continue

        dur_min = int(raw_slot.duration_minutes or place.recommended_duration_min or 90)
        transit_mode = normalize_transit_mode(raw_slot.transit_mode)
        raw_date_iso = raw_slot.visit_date.isoformat()

        weather_adapted = False
        adjustment_note: str | None = None
        validation_status: str = "VALID"

        # Règle météo stricte : ne jamais proposer un lieu en plein air un jour d'orage ou de pluie
        # (sauf si l'utilisateur l'a demandé via allow_outdoor_in_rain=True)
        if place.is_outdoor and not payload.allow_outdoor_in_rain and _is_rain_or_storm_date(raw_date_iso):
            moved_to_dry = False
            dry_dates = [d for d in trip_dates if not _is_rain_or_storm_date(d.isoformat())]
            for dry_d in dry_dates:
                cand_s_utc, cand_e_utc = parse_local_slot_to_utc(
                    visit_date=dry_d,
                    local_start_time_str=raw_slot.local_start_time,
                    duration_minutes=dur_min,
                    timezone_name=dest_tz,
                )
                dry_val = _validate_slot(
                    requested_start_utc=cand_s_utc,
                    duration_minutes=dur_min,
                    destination_timezone=dest_tz,
                    place_id=place.id,
                    place_name=place.name,
                    place_latitude=place.latitude,
                    place_longitude=place.longitude,
                    place_opening_hours=place.opening_hours or {},
                    trip_arrival_utc=trip_arr_utc,
                    trip_departure_utc=trip_dep_utc,
                    existing_items=draft_snapshots,
                    transit_mode=transit_mode,
                )
                if dry_val.valid:
                    chosen_start_utc = cand_s_utc
                    chosen_end_utc = cand_e_utc
                    validation_status = "CORRECTED"
                    weather_adapted = True
                    adjustment_note = (
                        f"Déplacé au {_format_date_fr(dry_d)} à {raw_slot.local_start_time} "
                        "en raison de la pluie ou de l'orage prévu"
                    )
                    adjustments_fr.append(f"{place.name} : {adjustment_note}")
                    moved_to_dry = True
                    break
                for sug in dry_val.suggested_slots:
                    if _is_rain_or_storm_date(sug.local_date):
                        continue
                    sug_s_utc = ensure_utc(sug.start_at_utc)
                    sug_e_utc = ensure_utc(sug.end_at_utc)
                    recheck_dry = _validate_slot(
                        requested_start_utc=sug_s_utc,
                        duration_minutes=dur_min,
                        destination_timezone=dest_tz,
                        place_id=place.id,
                        place_name=place.name,
                        place_latitude=place.latitude,
                        place_longitude=place.longitude,
                        place_opening_hours=place.opening_hours or {},
                        trip_arrival_utc=trip_arr_utc,
                        trip_departure_utc=trip_dep_utc,
                        existing_items=draft_snapshots,
                        transit_mode=transit_mode,
                    )
                    if recheck_dry.valid:
                        chosen_start_utc = sug_s_utc
                        chosen_end_utc = sug_e_utc
                        validation_status = "CORRECTED"
                        weather_adapted = True
                        sug_d = date.fromisoformat(sug.local_date)
                        adjustment_note = (
                            f"Déplacé au {_format_date_fr(sug_d)} à {sug.local_start_time} "
                            "en raison de la pluie ou de l'orage prévu"
                        )
                        adjustments_fr.append(f"{place.name} : {adjustment_note}")
                        moved_to_dry = True
                        break
                if moved_to_dry:
                    break

            if not moved_to_dry:
                adjustments_fr.append(
                    f"« {place.name} » retiré car lieu en plein air un jour d'orage ou de pluie."
                )
                continue
        else:
            req_start_utc, req_end_utc = parse_local_slot_to_utc(
                visit_date=raw_slot.visit_date,
                local_start_time_str=raw_slot.local_start_time,
                duration_minutes=dur_min,
                timezone_name=dest_tz,
            )

            val_res = _validate_slot(
                requested_start_utc=req_start_utc,
                duration_minutes=dur_min,
                destination_timezone=dest_tz,
                place_id=place.id,
                place_name=place.name,
                place_latitude=place.latitude,
                place_longitude=place.longitude,
                place_opening_hours=place.opening_hours or {},
                trip_arrival_utc=trip_arr_utc,
                trip_departure_utc=trip_dep_utc,
                existing_items=draft_snapshots,
                transit_mode=transit_mode,
            )

            chosen_start_utc = req_start_utc
            chosen_end_utc = req_end_utc

            if not val_res.valid:
                corrected = False
                candidate_suggestions = list(val_res.suggested_slots)
                if place.is_outdoor and not payload.allow_outdoor_in_rain:
                    extra_sugs = ItineraryValidationEngine.suggest_free_slots(
                        trip_arrival_utc=trip_arr_utc,
                        trip_departure_utc=trip_dep_utc,
                        destination_tz_name=dest_tz,
                        place_id=place.id,
                        place_name=place.name,
                        place_lat=place.latitude,
                        place_lng=place.longitude,
                        place_opening_hours=place.opening_hours or {},
                        preferred_start_utc=req_start_utc,
                        duration_minutes=dur_min,
                        transit_mode=transit_mode,
                        existing_visits=draft_snapshots,
                        max_suggestions=12,
                    )
                    seen_starts = {s.start_at_utc for s in candidate_suggestions}
                    for es in extra_sugs:
                        if es.start_at_utc not in seen_starts:
                            candidate_suggestions.append(es)

                for sug in candidate_suggestions:
                    if place.is_outdoor and not payload.allow_outdoor_in_rain and _is_rain_or_storm_date(sug.local_date):
                        continue
                    sug_start_utc = ensure_utc(sug.start_at_utc)
                    sug_end_utc = ensure_utc(sug.end_at_utc)
                    recheck = _validate_slot(
                        requested_start_utc=sug_start_utc,
                        duration_minutes=dur_min,
                        destination_timezone=dest_tz,
                        place_id=place.id,
                        place_name=place.name,
                        place_latitude=place.latitude,
                        place_longitude=place.longitude,
                        place_opening_hours=place.opening_hours or {},
                        trip_arrival_utc=trip_arr_utc,
                        trip_departure_utc=trip_dep_utc,
                        existing_items=draft_snapshots,
                        transit_mode=transit_mode,
                    )
                    if recheck.valid:
                        chosen_start_utc = sug_start_utc
                        chosen_end_utc = sug_end_utc
                        validation_status = "CORRECTED"
                        sug_d = date.fromisoformat(sug.local_date)
                        adjustment_note = _format_simple_slot_correction_fr(
                            place=place,
                            val_res=val_res,
                            sug_date=sug_d,
                            sug_start_hm=sug.local_start_time,
                            orig_date=raw_slot.visit_date,
                        )
                        adjustments_fr.append(f"{place.name} : {adjustment_note}")
                        corrected = True
                        break

                if not corrected:
                    adjustments_fr.append(
                        f"Créneau non disponible pour « {place.name} » à {raw_slot.local_start_time} (retiré)."
                    )
                    continue

        loc_s = to_destination_local(chosen_start_utc, dest_tz)
        loc_e = to_destination_local(chosen_end_utc, dest_tz)
        final_date_str = loc_s.strftime("%Y-%m-%d")

        # Garde-fou final : aucun lieu en plein air un jour d'orage ou de pluie
        if place.is_outdoor and not payload.allow_outdoor_in_rain and _is_rain_or_storm_date(final_date_str):
            continue

        final_day_w = weather_by_date.get(final_date_str, {})
        if final_day_w.get("available", True) and _is_rain_or_storm_date(final_date_str) and not place.is_outdoor:
            weather_adapted = True

        used_place_ids.add(place.id)
        draft_snapshots.append(
            ScheduledVisitSnapshot(
                item_id=f"draft-{idx}",
                place_id=place.id,
                place_name=place.name,
                latitude=place.latitude,
                longitude=place.longitude,
                start_at_utc=chosen_start_utc,
                end_at_utc=chosen_end_utc,
                transit_mode_to_next=transit_mode,
            )
        )
        accepted_slots.append(
            {
                "place": place,
                "start_utc": chosen_start_utc,
                "end_utc": chosen_end_utc,
                "loc_s": loc_s,
                "loc_e": loc_e,
                "duration_minutes": dur_min,
                "transit_mode": transit_mode,
                "validation_status": validation_status,
                "adjustment_note": adjustment_note,
                "weather_summary": str(final_day_w.get("summary") or "Prévision non disponible"),
                "weather_adapted": weather_adapted,
            }
        )

    unique_tastes_count = len({str(t).strip().upper() for t in (payload.tastes or []) if str(t).strip()})
    limited_places_notice_fr: str | None = None
    if len(db_places) < 12 or unique_tastes_count >= 4:
        limited_places_notice_fr = f"Peu de lieux disponibles à {destination.city_name} pour l'instant"
        if limited_places_notice_fr not in adjustments_fr:
            adjustments_fr.append(limited_places_notice_fr)

    accepted_slots.sort(key=lambda x: x["start_utc"])
    prev_by_day: dict[str, Place] = {}
    draft_items: list[AIDraftSlotSchema] = []
    total_transit_min = 0
    total_cost_eur = 0.0
    any_real_source = False

    for entry in accepted_slots:
        p: Place = entry["place"]
        d_str = entry["loc_s"].strftime("%Y-%m-%d")
        from_prev_min = 0
        from_prev_m = 0
        t_source = "ESTIMATED"
        t_label = "Temps estimé"

        if d_str in prev_by_day:
            prev_p = prev_by_day[d_str]
            leg = await registry.routing.compute_transit_leg(
                prev_p.latitude,
                prev_p.longitude,
                p.latitude,
                p.longitude,
                mode=entry["transit_mode"],
            )
            from_prev_min = int(leg["duration_minutes"])
            from_prev_m = int(leg["distance_meters"])
            t_source = str(leg.get("source", "ESTIMATED")).upper()
            t_label = str(leg.get("label_fr", "Temps réel" if t_source == "REAL" else "Temps estimé"))
            if t_source == "REAL":
                any_real_source = True
            total_transit_min += from_prev_min

        prev_by_day[d_str] = p
        cost_val = float(p.estimated_cost or 0.0)
        total_cost_eur += cost_val
        v_date_obj = entry["loc_s"].date()
        transit_label_fr = f"Trajet : ~{from_prev_min} min" if from_prev_min > 0 else None

        draft_items.append(
            AIDraftSlotSchema(
                place_id=p.id,
                place_name=p.name,
                place_category=p.category,
                is_outdoor=bool(p.is_outdoor),
                visit_date=v_date_obj,
                visit_date_label_fr=_format_date_fr(v_date_obj),
                local_start_time=entry["loc_s"].strftime("%H:%M"),
                local_end_time=entry["loc_e"].strftime("%H:%M"),
                start_at=entry["start_utc"],
                end_at=entry["end_utc"],
                duration_minutes=entry["duration_minutes"],
                estimated_cost_eur=cost_val,
                transit_mode=entry["transit_mode"],
                transit_from_prev_min=from_prev_min,
                transit_distance_from_prev_m=from_prev_m,
                transit_time_source=t_source,
                transit_source_label=t_label,
                transit_label_fr=transit_label_fr,
                weather_summary=entry["weather_summary"],
                weather_adapted=entry["weather_adapted"],
                validation_status=entry["validation_status"],
                adjustment_note_fr=entry["adjustment_note"],
                validated_by_engine=True,
            )
        )

    return AIGenerateItineraryDraftResponse(
        trip_id=trip.id,
        destination_city=destination.city_name,
        destination_timezone=dest_tz,
        persisted=False,
        calendar_synced=False,
        requires_user_confirmation=True,
        attempts_used=attempts_used,
        summary_fr=parsed_plan.summary_fr,
        pace=payload.pace,
        budget_eur=payload.budget_eur,
        tastes=payload.tastes,
        total_estimated_cost_eur=round(total_cost_eur, 2),
        total_transit_minutes=total_transit_min,
        routing_source_label="Temps réel" if any_real_source else "Temps estimé",
        limited_places_notice_fr=limited_places_notice_fr,
        adjustments_fr=adjustments_fr,
        draft_items=draft_items,
    )


@router.post("/trip/{trip_id}/ai-apply", response_model=TripItineraryScheduleResponse)
async def apply_ai_itinerary_draft(
    trip_id: str,
    payload: AIApplyDraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripItineraryScheduleResponse:
    """
    Valide et enregistre le brouillon IA après confirmation explicite de l'utilisateur,
    puis synchronise chaque visite avec Google Calendar.
    """
    trip, destination = await _load_trip_and_destination_strict(db, trip_id, current_user.id)
    dest_tz = destination.timezone or "UTC"
    registry = get_provider_registry()

    places_res = await db.scalars(select(Place).where(Place.destination_id == destination.id))
    places_by_id = {p.id: p for p in places_res.all()}

    existing_items, existing_places_map = await _load_trip_items_with_places(db, trip.id)
    working_snapshots: list[ScheduledVisitSnapshot] = (
        [] if payload.replace_existing else _build_snapshots(existing_items, existing_places_map)
    )

    validated_to_persist: list[tuple[Place, datetime, datetime, date, int, str]] = []
    for idx, slot in enumerate(payload.draft_items):
        place = places_by_id.get(slot.place_id)
        if not place:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Lieu inexistant en base pour cette destination : {slot.place_id}",
            )
        start_utc, end_utc = parse_local_slot_to_utc(
            visit_date=slot.visit_date,
            local_start_time_str=slot.local_start_time,
            duration_minutes=slot.duration_minutes,
            timezone_name=dest_tz,
        )
        t_mode = normalize_transit_mode(slot.transit_mode)
        val_res = _validate_slot(
            requested_start_utc=start_utc,
            duration_minutes=slot.duration_minutes,
            destination_timezone=dest_tz,
            place_id=place.id,
            place_name=place.name,
            place_latitude=place.latitude,
            place_longitude=place.longitude,
            place_opening_hours=place.opening_hours or {},
            trip_arrival_utc=ensure_utc(trip.arrival_at) if trip.arrival_at else None,
            trip_departure_utc=ensure_utc(trip.departure_at) if trip.departure_at else None,
            existing_items=working_snapshots,
            transit_mode=t_mode,
        )
        if not val_res.valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": val_res.reason_code,
                    "message": val_res.message,
                    "place_name": place.name,
                    "suggested_slots": [
                        SuggestedSlotSchema(**s.to_dict()).model_dump(mode="json")
                        for s in val_res.suggested_slots
                    ],
                },
            )
        working_snapshots.append(
            ScheduledVisitSnapshot(
                item_id=f"apply-{idx}",
                place_id=place.id,
                place_name=place.name,
                latitude=place.latitude,
                longitude=place.longitude,
                start_at_utc=start_utc,
                end_at_utc=end_utc,
                transit_mode_to_next=t_mode,
            )
        )
        validated_to_persist.append((place, start_utc, end_utc, slot.visit_date, slot.duration_minutes, t_mode))

    if payload.replace_existing:
        for old_item in existing_items:
            if old_item.google_calendar_event_id:
                try:
                    await registry.calendar.delete_visit_event(
                        calendar_id="primary",
                        event_id=old_item.google_calendar_event_id,
                    )
                except Exception:
                    pass
            await db.delete(old_item)
        await db.commit()

    created_items: list[tuple[ItineraryItem, Place]] = []
    for order_idx, (place, start_utc, end_utc, v_date, dur_min, t_mode) in enumerate(validated_to_persist):
        new_item = ItineraryItem(
            trip_id=trip.id,
            place_id=place.id,
            visit_date=v_date,
            start_at=start_utc,
            end_at=end_utc,
            duration_minutes=dur_min,
            day_order_index=order_idx + 1,
            transit_mode_to_next=t_mode,
            transit_duration_to_next_min=0,
            transit_distance_meters=0,
            transit_time_source="ESTIMATED",
            calendar_sync_status="PENDING_SYNC",
            calendar_sync_attempts=0,
            notes="Programme généré par IA et validé",
        )
        db.add(new_item)
        created_items.append((new_item, place))

    await db.commit()
    for item_obj, place_obj in created_items:
        await db.refresh(item_obj)
        await _sync_item_with_google_calendar(db, item_obj, place_obj, dest_tz, action="create")

    await _recompute_trip_day_transits(db, trip.id, dest_tz)
    return await get_trip_itinerary(trip_id=trip.id, current_user=current_user, db=db)


# ==============================================================================
# 3. ENDPOINTS ASSISTANT DE CHAT SÉCURISÉ & CONTRÔLÉ
# ==============================================================================
async def _build_safe_trip_context_for_chat(
    db: AsyncSession,
    trip: Trip,
    destination: Destination,
) -> tuple[dict[str, Any], dict[str, Place], list[ItineraryItem]]:
    """
    Construit le contexte du voyage pour l'assistant de chat en respectant strictement :
    1. Aucune donnée d'un autre utilisateur ni d'un autre voyage,
    2. Aucun document du coffre-fort (VaultDocument) ni jeton OAuth Google (google_oauth_tokens),
    3. Les descriptions de lieux sont encapsulées et nettoyées comme de simples données passives.
    """
    dest_tz = destination.timezone or "UTC"
    items, places_map = await _load_trip_items_with_places(db, trip.id)
    items.sort(key=lambda x: ensure_utc(x.start_at))

    flight_obj = await db.scalar(select(FlightBooking).where(FlightBooking.trip_id == trip.id))
    flight_data: dict[str, Any] | None = None
    if flight_obj:
        flight_data = {
            "airline": flight_obj.airline,
            "flight_number_outbound": flight_obj.flight_number_outbound,
            "flight_number_return": flight_obj.flight_number_inbound,
            "origin_iata": flight_obj.origin_iata,
            "destination_iata": flight_obj.destination_iata,
            "departure_at": ensure_utc(flight_obj.arrival_outbound_at).isoformat(),
            "return_at": ensure_utc(flight_obj.departure_inbound_at).isoformat(),
            "price": float(flight_obj.price),
            "currency": flight_obj.currency,
            "pnr_reference": flight_obj.pnr_reference,
        }

    acc_res = await db.scalars(
        select(Accommodation)
        .where(Accommodation.destination_id == destination.id)
        .order_by(Accommodation.rating.desc())
    )
    acc_obj = acc_res.first()
    acc_data: dict[str, Any] | None = None
    if acc_obj:
        acc_data = {
            "name": acc_obj.name,
            "type": acc_obj.type,
            "neighborhood": acc_obj.neighborhood,
            "nightly_price": float(acc_obj.price_per_night),
            "rating": acc_obj.rating,
        }

    dest_places_res = await db.scalars(
        select(Place).where(Place.destination_id == destination.id).order_by(Place.avg_rating.desc())
    )
    dest_places = list(dest_places_res.all())
    all_places_by_id = {p.id: p for p in dest_places}
    all_places_by_id.update(places_map)

    available_places_safe = [
        {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "is_outdoor": bool(p.is_outdoor),
            "recommended_duration_min": p.recommended_duration_min,
            "estimated_cost": float(p.estimated_cost or 0.0),
            "description_data": sanitize_external_data_for_llm(p.description),
        }
        for p in dest_places
    ]

    itinerary_safe: list[dict[str, Any]] = []
    visits_cost = 0.0
    for item in items:
        p = all_places_by_id.get(item.place_id)
        if not p:
            continue
        loc_s = to_destination_local(ensure_utc(item.start_at), dest_tz)
        loc_e = to_destination_local(ensure_utc(item.end_at), dest_tz)
        visits_cost += float(p.estimated_cost or 0.0)
        itinerary_safe.append(
            {
                "item_id": item.id,
                "place_id": p.id,
                "place_name": p.name,
                "category": p.category,
                "is_outdoor": bool(p.is_outdoor),
                "visit_date": loc_s.strftime("%Y-%m-%d"),
                "local_start_time": loc_s.strftime("%H:%M"),
                "local_end_time": loc_e.strftime("%H:%M"),
                "duration_minutes": item.duration_minutes,
                "transit_mode": normalize_transit_mode(item.transit_mode_to_next),
            }
        )

    trip_dates = _compute_trip_dates_local(trip, dest_tz)
    weather_days, _, _, _ = await _fetch_trip_weather_forecasts(
        destination=destination,
        trip_dates=trip_dates,
    )

    flight_cost = float(flight_obj.price) if flight_obj else 0.0
    planned_total = float(trip.total_budget_planned or 2000.0)
    safe_context = {
        "trip": {
            "id": trip.id,
            "city_name": destination.city_name,
            "timezone": dest_tz,
            "arrival_at": ensure_utc(trip.arrival_at).isoformat() if trip.arrival_at else None,
            "departure_at": ensure_utc(trip.departure_at).isoformat() if trip.departure_at else None,
            "travel_style": trip.travel_style,
            "total_budget_planned": planned_total,
            "currency": trip.currency,
        },
        "flight": flight_data,
        "accommodation": acc_data,
        "budget": {
            "planned_total": planned_total,
            "flight_cost": flight_cost,
            "visits_estimated_cost": round(visits_cost, 2),
            "remaining_estimated": round(max(0.0, planned_total - flight_cost - visits_cost), 2),
        },
        "weather": [w.model_dump() for w in weather_days],
        "itinerary": itinerary_safe,
        "available_places": available_places_safe,
    }
    return safe_context, all_places_by_id, items


def _serialize_chat_message(msg: ChatMessage) -> ChatMessageResponse:
    prop_obj: ChatProposedActionSchema | None = None
    if msg.proposed_action and isinstance(msg.proposed_action, dict):
        prop_obj = ChatProposedActionSchema(**msg.proposed_action)
    status_val = getattr(msg, "action_status", None) or "NONE"
    role_val = getattr(msg, "sender_role", "user")
    return ChatMessageResponse(
        id=msg.id,
        trip_id=msg.trip_id,
        role="assistant" if role_val == "assistant" else "user",
        content=msg.content,
        proposed_action=prop_obj,
        action_status=status_val,
        created_at=ensure_utc(msg.created_at),
    )


@router.get("/trip/{trip_id}/chat", response_model=ChatConversationResponse)
async def get_trip_chat_history(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatConversationResponse:
    trip, destination = await _load_trip_and_destination_strict(db, trip_id, current_user.id)
    res = await db.scalars(
        select(ChatMessage)
        .where(ChatMessage.trip_id == trip.id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = [_serialize_chat_message(m) for m in res.all()]
    return ChatConversationResponse(
        trip_id=trip.id,
        destination_city=destination.city_name,
        messages=messages,
        security_audit={
            "scoped_to_trip_id": trip.id,
            "owner_user_id": current_user.id,
            "vault_documents_exposed_to_model": False,
            "google_oauth_tokens_exposed_to_model": False,
            "external_place_content_delimited_as_data": True,
        },
    )


@router.delete("/trip/{trip_id}/chat", response_model=ChatConversationResponse)
@router.post("/trip/{trip_id}/chat/reset", response_model=ChatConversationResponse)
async def reset_trip_chat_history(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatConversationResponse:
    """
    Réinitialise la conversation de l'assistant pour ce voyage ("Nouvelle conversation") :
    supprime l'historique des messages du chat sans toucher aux visites du programme.
    """
    trip, destination = await _load_trip_and_destination_strict(db, trip_id, current_user.id)
    await db.execute(delete(ChatMessage).where(ChatMessage.trip_id == trip.id))
    await db.commit()
    return ChatConversationResponse(
        trip_id=trip.id,
        destination_city=destination.city_name,
        messages=[],
        security_audit={
            "scoped_to_trip_id": trip.id,
            "owner_user_id": current_user.id,
            "vault_documents_exposed_to_model": False,
            "google_oauth_tokens_exposed_to_model": False,
            "external_place_content_delimited_as_data": True,
        },
    )


def _is_informational_places_request(raw_msg: str) -> bool:
    """Détecte une question d'information demandant d'autres lieux à visiter qui ne sont pas au programme."""
    msg_lower = raw_msg.strip().lower()
    return bool(
        re.search(
            r"(autres?\s+lieux?|pas\s+(encore\s+)?(mis|ajout[ée]|planifi[ée]|pr[ée]vu)?\s*(dans|au)\s+(mon\s+|le\s+)?programme|"
            r"(quels?|quelles?)\s+(sont\s+les\s+)?(autres?\s+)?(lieux|visites|activit[ée]s|endroits|monuments|mus[ée]es|restaurants)|"
            r"(que|quoi)\s+(puis[- ]je|je\s+peux|peut[- ]on|on\s+peut)?\s*(visiter|voir|faire)|"
            r"(donne|donner|montre|montrer|liste|lister|sugg[èe]re|conseille|recommande)\b.*\b(lieux|visites|endroits|id[ée]es|activit[ée]s)|"
            r"\bid[ée]es?\s+de\s+(visites?|lieux|sorties?)\b)",
            msg_lower,
        )
    )


def _format_unscheduled_places_info(
    city_name: str,
    places_by_id: dict[str, Place],
    existing_items: list[ItineraryItem],
) -> str:
    """
    Construit la réponse INFO obligatoire avec la liste des lieux de la ville présents en base,
    en excluant ceux déjà au programme (nom, catégorie, durée, intérieur/extérieur),
    et la proposition d'en ajouter un.
    """
    scheduled_place_ids = {str(it.place_id) for it in existing_items if it.place_id}
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
    lines: list[str] = []
    for p in places_by_id.values():
        if str(p.id) in scheduled_place_ids:
            continue
        cat_fr = cat_map_fr.get(str(p.category or "").upper(), str(p.category or "Culture").capitalize())
        env_fr = "Extérieur" if p.is_outdoor else "Intérieur"
        dur_min = int(p.recommended_duration_min or 90)
        lines.append(f"• {p.name} — {cat_fr}, durée conseillée : {dur_min} min, {env_fr}")

    if not lines:
        return f"Tous les lieux enregistrés à {city_name} figurent déjà dans votre programme."

    return (
        f"Voici d'autres lieux à visiter à {city_name} qui ne sont pas dans votre programme :\n"
        + "\n".join(lines)
        + "\n\nSouhaitez-vous en ajouter un à votre programme ? Indiquez-moi son nom ainsi que le jour et l'heure souhaités."
    )


def _validate_and_normalize_chat_llm_payload(raw_res: Any) -> dict[str, Any]:
    """
    Valide strictement la réponse brute du fournisseur IA (Ollama/mistral ou simulé) :
    - Rejette tout JSON malformé, tout type non-dict ou toute clé/valeur hors schéma.
    - Actions autorisées uniquement : ADD, ADD_VISIT, MOVE, MOVE_VISIT, REMOVE, REMOVE_VISIT, INFO, ASK, NONE, None.
    - Format de date strict : YYYY-MM-DD (si fourni).
    - Format d'heure strict : HH:MM ou HhMM entre 00:00 et 23:59 (si fourni).
    """
    if isinstance(raw_res, str):
        try:
            raw_res = json.loads(raw_res)
        except Exception as exc:
            raise ValueError(f"JSON invalide renvoyé par le modèle : {exc}") from exc

    if not isinstance(raw_res, dict) or not raw_res:
        raise ValueError("Réponse hors schéma : un objet JSON non vide est requis.")

    allowed_keys = {
        "reply",
        "message",
        "proposed_action",
        "action_type",
        "action",
        "type",
        "item_id",
        "place_id",
        "place_name",
        "place",
        "lieu",
        "visit_date",
        "date",
        "local_start_time",
        "start_time",
        "time",
        "heure",
        "duration_minutes",
        "duration",
        "transit_mode",
        "info_subtype",
    }
    unknown_top = set(raw_res.keys()) - allowed_keys
    if unknown_top:
        raise ValueError(f"Clés hors schéma au premier niveau : {sorted(unknown_top)}")

    if not any(k in raw_res for k in ("reply", "message", "proposed_action", "action_type", "action", "type")):
        raise ValueError("Réponse hors schéma : aucune clé d'action ou de réponse reconnue.")

    reply_val = raw_res.get("reply") if "reply" in raw_res else raw_res.get("message")
    if reply_val is not None and not isinstance(reply_val, str):
        raise ValueError("Champ 'reply' hors schéma (doit être une chaîne).")

    has_nested = "proposed_action" in raw_res
    nested_pa = raw_res.get("proposed_action")
    if has_nested and nested_pa is not None and not isinstance(nested_pa, dict):
        raise ValueError("Champ 'proposed_action' hors schéma (doit être un objet ou null).")

    if isinstance(nested_pa, dict):
        unknown_nested = set(nested_pa.keys()) - allowed_keys
        if unknown_nested:
            raise ValueError(f"Clés hors schéma dans proposed_action : {sorted(unknown_nested)}")
        act_src = nested_pa
    elif has_nested and nested_pa is None and not any(k in raw_res for k in ("action_type", "action", "type")):
        return {
            "action_type": "NONE",
            "reply": str(reply_val or "Je n'ai pas compris. Voulez-vous ajouter, déplacer ou retirer une visite ?"),
            "proposed_action": None,
        }
    else:
        act_src = raw_res

    raw_act = (
        act_src.get("action_type")
        if "action_type" in act_src
        else (act_src.get("action") if "action" in act_src else act_src.get("type"))
    )
    if raw_act is None:
        return {
            "action_type": "NONE",
            "reply": str(reply_val or "Je n'ai pas compris. Voulez-vous ajouter, déplacer ou retirer une visite ?"),
            "proposed_action": None,
        }
    if not isinstance(raw_act, str):
        raise ValueError(f"action_type hors schéma (type invalide) : {raw_act!r}")

    act_upper = raw_act.strip().upper()
    action_map = {
        "ADD": "ADD_VISIT",
        "ADD_VISIT": "ADD_VISIT",
        "MOVE": "MOVE_VISIT",
        "MOVE_VISIT": "MOVE_VISIT",
        "REMOVE": "REMOVE_VISIT",
        "REMOVE_VISIT": "REMOVE_VISIT",
        "DELETE": "REMOVE_VISIT",
        "INFO": "INFO",
        "INFO_PLACES": "INFO",
        "LIST": "INFO",
        "SUGGEST": "INFO",
        "ASK": "ASK",
        "QUESTION": "ASK",
        "NONE": "NONE",
        "": "NONE",
    }
    if act_upper not in action_map:
        raise ValueError(f"Valeur action_type hors schéma : {raw_act!r}")
    norm_act = action_map[act_upper]

    if norm_act == "INFO":
        return {
            "action_type": "INFO",
            "info_subtype": raw_res.get("info_subtype"),
            "place_name": raw_res.get("place_name"),
            "reply": str(reply_val or ""),
            "proposed_action": None,
        }

    raw_date = act_src.get("visit_date") if "visit_date" in act_src else act_src.get("date")
    norm_date: str | None = None
    if raw_date is not None and raw_date != "":
        if not isinstance(raw_date, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", raw_date.strip()):
            raise ValueError(f"visit_date hors schéma : {raw_date!r}")
        try:
            date.fromisoformat(raw_date.strip())
        except ValueError as exc:
            raise ValueError(f"visit_date invalide : {raw_date!r}") from exc
        norm_date = raw_date.strip()

    raw_time = (
        act_src.get("local_start_time")
        if "local_start_time" in act_src
        else (
            act_src.get("start_time")
            if "start_time" in act_src
            else (act_src.get("time") if "time" in act_src else act_src.get("heure"))
        )
    )
    norm_time: str | None = None
    if raw_time is not None and raw_time != "":
        if not isinstance(raw_time, str):
            raise ValueError(f"local_start_time hors schéma : {raw_time!r}")
        tm = re.match(r"^(\d{1,2})(?::|[hH])(\d{2})?$", raw_time.strip())
        if not tm:
            raise ValueError(f"local_start_time hors schéma : {raw_time!r}")
        hh = int(tm.group(1))
        mm = int(tm.group(2) or 0)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError(f"local_start_time hors plage 00:00-23:59 : {raw_time!r}")
        norm_time = f"{hh:02d}:{mm:02d}"

    raw_dur = act_src.get("duration_minutes") if "duration_minutes" in act_src else act_src.get("duration")
    norm_dur: int | None = None
    if raw_dur is not None:
        if isinstance(raw_dur, bool) or not isinstance(raw_dur, int) or not (15 <= raw_dur <= 720):
            raise ValueError(f"duration_minutes hors schéma : {raw_dur!r}")
        norm_dur = raw_dur

    raw_tmode = act_src.get("transit_mode")
    norm_tmode = "METRO"
    if raw_tmode is not None and raw_tmode != "":
        if not isinstance(raw_tmode, str) or raw_tmode.strip().upper() not in {
            "WALKING",
            "METRO",
            "CAR",
            "BUS",
            "TRANSIT",
            "TAXI",
            "BIKE",
            "TRAIN",
            "TRAM",
        }:
            raise ValueError(f"transit_mode hors schéma : {raw_tmode!r}")
        norm_tmode = normalize_transit_mode(raw_tmode.strip().upper())

    raw_pname = (
        act_src.get("place_name")
        if "place_name" in act_src
        else (act_src.get("place") if "place" in act_src else act_src.get("lieu"))
    )
    if raw_pname is not None and not isinstance(raw_pname, str):
        raise ValueError(f"place_name hors schéma : {raw_pname!r}")

    raw_pid = act_src.get("place_id")
    if raw_pid is not None and not isinstance(raw_pid, str):
        raise ValueError(f"place_id hors schéma : {raw_pid!r}")

    raw_iid = act_src.get("item_id")
    if raw_iid is not None and not isinstance(raw_iid, str):
        raise ValueError(f"item_id hors schéma : {raw_iid!r}")

    if norm_act in {"ASK", "NONE"}:
        return {
            "action_type": norm_act,
            "place_name": raw_pname.strip() if isinstance(raw_pname, str) and raw_pname.strip() else None,
            "visit_date": norm_date,
            "local_start_time": norm_time,
            "reply": str(
                reply_val
                or "Je n'ai pas compris. Voulez-vous ajouter, déplacer ou retirer une visite ?"
            ),
            "proposed_action": None,
        }

    return {
        "action_type": norm_act,
        "reply": str(reply_val or ""),
        "proposed_action": {
            "action_type": norm_act,
            "item_id": raw_iid,
            "place_id": raw_pid,
            "place_name": raw_pname.strip() if isinstance(raw_pname, str) and raw_pname.strip() else None,
            "visit_date": norm_date,
            "local_start_time": norm_time,
            "duration_minutes": norm_dur,
            "transit_mode": norm_tmode,
        },
    }


@router.post("/trip/{trip_id}/chat", response_model=ChatConversationResponse)
async def send_trip_chat_message(
    trip_id: str,
    payload: ChatSendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatConversationResponse:
    """
    Envoie un message à l'assistant du voyage :
    - Stratégie configurable AI_CHAT_STRATEGY=rules (défaut) | hybrid | model :
      en mode rules, aucun appel à Ollama et aucune dépendance réseau externe.
    - Contrôle d'accès strict (403 si le voyage appartient à un autre utilisateur),
    - Historique limité aux 6 derniers échanges envoyés au modèle,
    - Résumé du séjour (visites, budget, météo) toujours recalculé en direct à chaque demande,
    - Action INFO obligatoire pour les questions d'information (autres lieux, météo, budget, horaires),
    - Anti-doublon : refuse un même lieu deux fois sauf demande explicite ("ajoute-le une deuxième fois"),
    - Journalisation fournisseur/modèle/durée à chaque message et aucun repli silencieux vers le simulateur quand AI_CHAT_STRATEGY=model et AI_PROVIDER_MODE=real.
    """
    registry = get_provider_registry()
    settings = get_settings()
    trip, destination = await _load_trip_and_destination_strict(db, trip_id, current_user.id)
    dest_tz = destination.timezone or "UTC"

    hist_res = await db.scalars(
        select(ChatMessage)
        .where(ChatMessage.trip_id == trip.id)
        .order_by(ChatMessage.created_at.asc())
    )
    history_rows = list(hist_res.all())

    # Historique limité aux 6 derniers échanges envoyés au modèle
    recent_history_rows = history_rows[-6:]
    history_for_ai = [{"role": m.sender_role, "content": m.content} for m in recent_history_rows]

    # Résumé du séjour (visites, budget, météo) toujours recalculé en direct depuis la base
    safe_context, places_by_id, existing_items = await _build_safe_trip_context_for_chat(
        db, trip, destination
    )

    # Détermination du dernier lieu évoqué dans les derniers échanges ou planifié au programme
    last_context_place: Place | None = None
    last_context_date: str | None = None
    last_context_time: str | None = None

    for prev_msg in reversed(recent_history_rows):
        if isinstance(prev_msg.proposed_action, dict):
            prev_pid = prev_msg.proposed_action.get("place_id")
            prev_pname = prev_msg.proposed_action.get("place_name")
            if prev_pid and str(prev_pid) in places_by_id:
                last_context_place = places_by_id[str(prev_pid)]
                last_context_date = prev_msg.proposed_action.get("visit_date")
                last_context_time = prev_msg.proposed_action.get("local_start_time")
                break
            if prev_pname:
                for p in places_by_id.values():
                    if p.name.lower() == str(prev_pname).strip().lower():
                        last_context_place = p
                        last_context_date = prev_msg.proposed_action.get("visit_date")
                        last_context_time = prev_msg.proposed_action.get("local_start_time")
                        break
            if last_context_place is not None:
                break
        msg_txt_low = (prev_msg.content or "").lower()
        for p in places_by_id.values():
            if p.name.lower() in msg_txt_low:
                last_context_place = p
                break
        if last_context_place is not None:
            break

    if last_context_place is None and existing_items:
        last_item = existing_items[-1]
        last_context_place = places_by_id.get(last_item.place_id)
        loc_last = to_destination_local(ensure_utc(last_item.start_at), dest_tz)
        last_context_date = loc_last.strftime("%Y-%m-%d")
        last_context_time = loc_last.strftime("%H:%M")

    if last_context_place is not None:
        # Toujours recalculer la date/heure réelle si le lieu est déjà au programme
        sched_for_last = next(
            (it for it in reversed(existing_items) if it.place_id == last_context_place.id),
            None,
        )
        if sched_for_last is not None:
            loc_sched = to_destination_local(ensure_utc(sched_for_last.start_at), dest_tz)
            last_context_date = loc_sched.strftime("%Y-%m-%d")
            last_context_time = loc_sched.strftime("%H:%M")
        safe_context["last_place_id"] = last_context_place.id
        safe_context["last_place_name"] = last_context_place.name
        safe_context["last_place_date"] = last_context_date
        safe_context["last_place_time"] = last_context_time

    safe_context["prompt"] = build_chat_assistant_prompt(
        user_message=payload.message.strip(),
        safe_trip_context=safe_context,
        chat_history=history_for_ai,
    )

    user_msg = ChatMessage(
        trip_id=trip.id,
        sender_role="user",
        content=payload.message.strip(),
        proposed_action=None,
        action_status="NONE",
    )
    db.add(user_msg)

    trip_dates = _compute_trip_dates_local(trip, dest_tz)

    def _norm_txt_local(s: str) -> str:
        s_clean = str(s).lower().replace("œ", "oe").replace("æ", "ae")
        s_dec = unicodedata.normalize("NFD", s_clean)
        s_no_acc = "".join(c for c in s_dec if unicodedata.category(c) != "Mn")
        return re.sub(r"[^a-z0-9]+", " ", s_no_acc).strip()

    def _spaceless_local(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", _norm_txt_local(s))

    def _resolve_named_trip_date(raw_msg: str) -> date | None:
        lower = raw_msg.lower()
        iso_m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", raw_msg)
        if iso_m:
            try:
                return date.fromisoformat(iso_m.group(1))
            except ValueError:
                pass

        base_d = trip_dates[0]
        if re.search(r"\bapr[èe]s[- ]demain\b", lower):
            return trip_dates[2] if len(trip_dates) > 2 else base_d + timedelta(days=2)
        if re.search(r"\bdemain\b", lower):
            return trip_dates[1] if len(trip_dates) > 1 else base_d + timedelta(days=1)
        if re.search(r"\baujourd['’ ]?hui\b", lower):
            return trip_dates[0]

        jour_m = re.search(r"\bjour\s*(\d{1,2})\b", lower)
        if jour_m:
            idx = int(jour_m.group(1)) - 1
            if 0 <= idx < len(trip_dates):
                return trip_dates[idx]

        slash_m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?\b", lower)
        if slash_m:
            day_num = int(slash_m.group(1))
            month_num = int(slash_m.group(2))
            year_num = int(slash_m.group(3)) if slash_m.group(3) else base_d.year
            for d_obj in trip_dates:
                if d_obj.day == day_num and d_obj.month == month_num:
                    return d_obj
            try:
                return date(year_num, month_num, day_num)
            except ValueError:
                pass

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
            word_norm = _norm_txt_local(dm_m.group(2))
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
                for d_obj in trip_dates:
                    if d_obj.day == day_num and d_obj.month == matched_month:
                        return d_obj
                try:
                    return date(base_d.year, matched_month, day_num)
                except ValueError:
                    pass

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
            for tok in _norm_txt_local(raw_msg).split():
                if len(tok) < 5:
                    continue
                for wd_name, wd_idx in weekday_map.items():
                    if SequenceMatcher(None, tok, wd_name).ratio() >= 0.84:
                        target_wd = wd_idx
        if target_wd is not None:
            for d_obj in trip_dates:
                if d_obj.weekday() == target_wd:
                    return d_obj
            delta_days = (target_wd - base_d.weekday()) % 7
            return base_d + timedelta(days=delta_days)

        return None

    def _extract_time_from_msg(raw_msg: str) -> str | None:
        cleaned = re.sub(r"\b20\d{2}-\d{2}-\d{2}\b", " ", raw_msg.lower())
        cleaned = re.sub(r"\b\d{1,2}/\d{1,2}(?:/20\d{2})?\b", " ", cleaned)
        if re.search(r"\bmidi\b", cleaned):
            return "12:00"
        if re.search(r"\bminuit\b", cleaned):
            return "00:00"
        m = re.search(r"\b(\d{1,2})\s*(?:h|heures?|:)\s*(\d{2})?\b", cleaned)
        if not m:
            return None
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}"
        return None

    def _fmt_short_time_fr(hm: str) -> str:
        try:
            parts = str(hm).strip().split(":")
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
            return f"{hh}h" if mm == 0 else f"{hh}h{mm:02d}"
        except Exception:
            return str(hm)

    def _resolve_place_obj(raw_action_dict: dict[str, Any], raw_msg: str) -> Place | None:
        pid = str(raw_action_dict.get("place_id") or "").strip()
        if pid and pid in places_by_id:
            return places_by_id[pid]

        pname = str(raw_action_dict.get("place_name") or "").strip().lower()
        if pname:
            pname_norm = _norm_txt_local(pname)
            pname_space = _spaceless_local(pname)
            for p in places_by_id.values():
                if p.name.lower() == pname or _norm_txt_local(p.name) == pname_norm:
                    return p
            for p in places_by_id.values():
                p_norm = _norm_txt_local(p.name)
                p_space = _spaceless_local(p.name)
                if (
                    pname in p.name.lower()
                    or p.name.lower() in pname
                    or (pname_space and (pname_space in p_space or p_space in pname_space))
                    or SequenceMatcher(None, pname_norm, p_norm).ratio() >= 0.76
                ):
                    return p

        iid = str(raw_action_dict.get("item_id") or "").strip()
        if iid:
            for it in existing_items:
                if it.id == iid and it.place_id in places_by_id:
                    return places_by_id[it.place_id]

        msg_norm_local = _norm_txt_local(raw_msg)
        msg_space_local = _spaceless_local(raw_msg)
        best_p: Place | None = None
        best_sc = 0.0
        stopwords = {"le", "la", "les", "l", "de", "du", "des", "d", "au", "aux", "el", "al"}
        heads = {"palais", "jardin", "jardins", "musee", "place", "mosquee", "parc", "cafe", "tombeaux", "medersa"}
        msg_toks = [t for t in msg_norm_local.split() if len(t) >= 3 and not t.isdigit()]
        for p in places_by_id.values():
            p_norm = _norm_txt_local(p.name)
            p_space = _spaceless_local(p.name)
            p_core = [t for t in p_norm.split() if t not in stopwords and len(t) >= 2]
            p_spec = [t for t in p_core if t not in heads and len(t) >= 3] or list(p_core)
            for i in range(len(p_core) - 1):
                comp = p_core[i] + p_core[i + 1]
                if len(comp) >= 5 and comp not in p_spec:
                    p_spec.append(comp)
            sc = 0.0
            if p_norm in msg_norm_local:
                sc = 1.0
            elif len(p_space) >= 6 and p_space in msg_space_local:
                sc = 0.98
            else:
                for sp in p_spec:
                    if sp in msg_toks:
                        sc = max(sc, 0.88)
                    else:
                        best_r = max((SequenceMatcher(None, sp, mt).ratio() for mt in msg_toks), default=0.0)
                        if best_r >= 0.78:
                            sc = max(sc, 0.80 * best_r)
            if sc >= 0.72 and sc > best_sc:
                best_sc = sc
                best_p = p
        if best_p is not None:
            return best_p

        if last_context_place is not None:
            return last_context_place
        return None

    named_trip_date = _resolve_named_trip_date(payload.message)
    msg_extracted_time = _extract_time_from_msg(payload.message)
    is_info_places_question = _is_informational_places_request(payload.message)

    chat_strategy = str(settings.AI_CHAT_STRATEGY or "rules")
    is_custom_test_provider = not isinstance(registry.ai, (SimulatedAIProvider, RealAIProvider))
    rules_provider = SimulatedAIProvider(settings)

    if is_custom_test_provider:
        active_provider = registry.ai
        provider_cls_name = type(registry.ai).__name__
        provider_mode = str(getattr(registry.ai, "mode", settings.AI_PROVIDER_MODE or "simulated"))
        model_name = settings.OLLAMA_MODEL if provider_mode == "real" else "simulated-deterministic"
    elif chat_strategy == "rules":
        # Mode rules (défaut) : aucun appel à Ollama, aucune dépendance réseau externe
        active_provider = rules_provider
        provider_cls_name = "SimulatedAIProvider"
        provider_mode = "rules"
        model_name = "rules-deterministic"
    else:
        active_provider = registry.ai
        provider_cls_name = type(registry.ai).__name__
        provider_mode = str(getattr(registry.ai, "mode", settings.AI_PROVIDER_MODE or "simulated"))
        model_name = settings.OLLAMA_MODEL if provider_mode == "real" else "simulated-deterministic"

    # En mode hybrid : on exécute d'abord l'analyseur à règles et on n'appelle le modèle que si rules renvoie ASK
    validated_ai: dict[str, Any] | None = None
    if not is_custom_test_provider and chat_strategy == "hybrid":
        t0_hyb = time.perf_counter()
        raw_rules_hyb = await rules_provider.generate_chat_reply(
            user_message=payload.message.strip(),
            safe_trip_context=safe_context,
            chat_history=history_for_ai,
        )
        dur_hyb = round((time.perf_counter() - t0_hyb) * 1000, 2)
        cand_hyb = _validate_and_normalize_chat_llm_payload(raw_rules_hyb)
        if cand_hyb.get("action_type") in {"ADD_VISIT", "MOVE_VISIT", "REMOVE_VISIT", "INFO"} or provider_mode != "real":
            validated_ai = cand_hyb
            logger.info(
                "[CHAT_AI] strategy=hybrid(rules) | provider=SimulatedAIProvider | mode=rules | model=rules-deterministic | duration_ms=%.2f | attempt=1 | trip_id=%s",
                dur_hyb,
                trip.id,
            )

    # Appel du fournisseur IA actif (si non déjà résolu par hybrid) avec validation stricte du schéma (2 essais max)
    max_attempts = 2
    last_provider_runtime_error: Exception | None = None

    if validated_ai is None:
        for _attempt in range(1, max_attempts + 1):
            t0 = time.perf_counter()
            try:
                raw_ai_result = await active_provider.generate_chat_reply(
                    user_message=payload.message.strip(),
                    safe_trip_context=safe_context,
                    chat_history=history_for_ai,
                )
                duration_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    "[CHAT_AI] strategy=%s | provider=%s | mode=%s | model=%s | duration_ms=%.2f | attempt=%d | trip_id=%s",
                    chat_strategy,
                    provider_cls_name,
                    provider_mode,
                    model_name,
                    duration_ms,
                    _attempt,
                    trip.id,
                )
            except Exception as exc:
                duration_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.error(
                    "[CHAT_AI] strategy=%s | provider=%s | mode=%s | model=%s | duration_ms=%.2f | attempt=%d | trip_id=%s | error=%s",
                    chat_strategy,
                    provider_cls_name,
                    provider_mode,
                    model_name,
                    duration_ms,
                    _attempt,
                    trip.id,
                    exc,
                )
                last_provider_runtime_error = exc
                if provider_mode == "real" and chat_strategy == "model":
                    # Interdiction stricte du repli silencieux vers le simulateur quand AI_CHAT_STRATEGY=model et AI_PROVIDER_MODE=real
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=(
                            f"Fournisseur IA réel ({provider_cls_name}, modèle={model_name}) indisponible "
                            f"(repli vers le simulateur interdit) : {exc}"
                        ),
                    ) from exc
                validated_ai = None
                continue

            try:
                validated_ai = _validate_and_normalize_chat_llm_payload(raw_ai_result)
                break
            except ValueError as val_exc:
                logger.warning(
                    "[CHAT_AI_SCHEMA] strategy=%s | provider=%s | mode=%s | model=%s | attempt=%d | schema_error=%s",
                    chat_strategy,
                    provider_cls_name,
                    provider_mode,
                    model_name,
                    _attempt,
                    val_exc,
                )
                validated_ai = None
                continue

    is_info_reply = False
    is_duplicate_refusal = False

    # Point 1 : Question d'information (autres lieux, horaires, météo, budget) -> Action INFO sans modification
    if is_info_places_question or (
        validated_ai is not None
        and validated_ai.get("action_type") == "INFO"
        and validated_ai.get("info_subtype") in (None, "PLACES")
        and not validated_ai.get("reply")
    ):
        reply_text = _format_unscheduled_places_info(
            destination.city_name, places_by_id, existing_items
        )
        raw_action = None
        is_info_reply = True
    elif validated_ai is not None and validated_ai.get("action_type") == "INFO":
        if validated_ai.get("info_subtype") == "PLACES":
            reply_text = _format_unscheduled_places_info(
                destination.city_name, places_by_id, existing_items
            )
        else:
            reply_text = str(validated_ai.get("reply") or "").strip() or _format_unscheduled_places_info(
                destination.city_name, places_by_id, existing_items
            )
        raw_action = None
        is_info_reply = True
    elif validated_ai is None:
        reply_text = "Je n'ai pas compris. Voulez-vous ajouter, déplacer ou retirer une visite ?"
        raw_action = None
    else:
        reply_text = str(
            validated_ai.get("reply")
            or "Je n'ai pas compris. Voulez-vous ajouter, déplacer ou retirer une visite ?"
        )
        raw_action = validated_ai.get("proposed_action")

    # Point 3 : Le message "Modification confirmée et appliquée" ne doit JAMAIS apparaître avant un clic sur Confirmer
    reply_text = re.sub(
        r"modification\s+confirm[ée]e\s+et\s+appliqu[ée]e\.?",
        "",
        reply_text,
        flags=re.IGNORECASE,
    ).strip()

    proposed_action_dict: dict[str, Any] | None = None
    action_status = "NONE"

    msg_lower_clean = payload.message.strip().lower()
    explicit_second_time = bool(
        re.search(
            r"\b(deuxi[èe]me\s+fois|2\s*e\s+fois|2\s*[èe]me\s+fois|seconde\s+fois|encore\s+une\s+fois)\b",
            msg_lower_clean,
        )
    )
    has_explicit_add_verb = bool(
        re.search(r"\b(ajoute|ajouter|rajoute|rajouter)\b", msg_lower_clean)
    ) and not any(
        kw in msg_lower_clean for kw in ("déplace", "deplace", "déplacer", "deplacer", "décale", "decale")
    )

    if isinstance(raw_action, dict) and raw_action.get("action_type") in {
        "ADD_VISIT",
        "MOVE_VISIT",
        "REMOVE_VISIT",
    }:
        act_type = str(raw_action["action_type"])
        place_obj = _resolve_place_obj(raw_action, payload.message)
        place_id = place_obj.id if place_obj is not None else str(raw_action.get("place_id") or "")
        item_id = raw_action.get("item_id")

        # Recherche d'une visite existante au programme pour ce lieu ou cet item_id
        matching_existing_item: ItineraryItem | None = None
        if item_id:
            matching_existing_item = next(
                (it for it in existing_items if it.id == str(item_id)),
                None,
            )
        if matching_existing_item is None and place_obj is not None:
            matching_existing_item = next(
                (it for it in reversed(existing_items) if it.place_id == place_obj.id),
                None,
            )

        # Règles côté code (Point 2) :
        # - Si l'utilisateur demande explicitement "ajoute-le une deuxième fois", on garde ADD_VISIT avec allow_duplicate=True.
        # - Si l'utilisateur utilise un verbe d'ajout explicite ("ajoute ...") pour un lieu déjà au programme sans dire
        #   "une deuxième fois", on garde ADD_VISIT avec allow_duplicate=False afin que le moteur de validation refuse le doublon.
        # - Dans tous les autres cas où le lieu est déjà au programme (ex. "on le mets à 12h", "déplace le Met à 14h"),
        #   ADD devient MOVE_VISIT sur la visite existante.
        if matching_existing_item is not None and act_type in {"ADD_VISIT", "MOVE_VISIT"}:
            if explicit_second_time:
                act_type = "ADD_VISIT"
                item_id = None
            elif has_explicit_add_verb and act_type == "ADD_VISIT":
                act_type = "ADD_VISIT"
                item_id = None
            else:
                act_type = "MOVE_VISIT"
                item_id = matching_existing_item.id

        v_time_str = str(msg_extracted_time or raw_action.get("local_start_time") or last_context_time or "14:00")
        dur_min = int(
            raw_action.get("duration_minutes") or (place_obj.recommended_duration_min if place_obj else 90)
        )
        t_mode = normalize_transit_mode(str(raw_action.get("transit_mode") or "METRO"))

        # Règle côté code 2 : une date absente du message n'est jamais acceptée telle quelle
        # (reprendre la date de la visite existante, sinon poser une question)
        v_date_str: str | None = None
        if act_type == "REMOVE_VISIT":
            if matching_existing_item is not None:
                v_date_str = to_destination_local(
                    ensure_utc(matching_existing_item.start_at), dest_tz
                ).strftime("%Y-%m-%d")
                item_id = matching_existing_item.id
            else:
                v_date_str = (
                    named_trip_date.isoformat()
                    if named_trip_date is not None
                    else str(raw_action.get("visit_date") or trip_dates[0].isoformat())
                )
        elif named_trip_date is not None:
            v_date_str = named_trip_date.isoformat()
        elif matching_existing_item is not None:
            v_date_str = to_destination_local(
                ensure_utc(matching_existing_item.start_at), dest_tz
            ).strftime("%Y-%m-%d")
        else:
            # Date absente du message et aucune visite existante au programme pour ce lieu -> poser une question (ASK)
            v_date_str = None
            if place_obj is not None:
                reply_text = (
                    f"Quel jour souhaitez-vous planifier la visite de « {place_obj.name} » "
                    f"à {_fmt_short_time_fr(v_time_str)} ?"
                )
            else:
                reply_text = (
                    "Quel lieu souhaitez-vous planifier ou modifier, et pour quel jour du séjour ?"
                )

        if act_type == "REMOVE_VISIT" and v_date_str is not None:
            proposed_action_dict = {
                "action_type": "REMOVE_VISIT",
                "item_id": item_id,
                "place_id": place_id,
                "place_name": place_obj.name if place_obj else str(raw_action.get("place_name") or "Visite"),
                "visit_date": v_date_str,
                "local_start_time": v_time_str,
                "local_end_time": None,
                "duration_minutes": dur_min,
                "transit_mode": t_mode,
                "validated_by_engine": True,
                "validation_error_code": None,
                "validation_message_fr": None,
                "suggested_slots": [],
            }
            action_status = "PENDING_CONFIRMATION"
        elif place_obj is not None and v_date_str is not None:
            v_date_obj = date.fromisoformat(v_date_str)
            req_start_utc, req_end_utc = parse_local_slot_to_utc(
                visit_date=v_date_obj,
                local_start_time_str=v_time_str,
                duration_minutes=dur_min,
                timezone_name=dest_tz,
            )
            loc_end_str = to_destination_local(req_end_utc, dest_tz).strftime("%H:%M")
            snapshots = _build_snapshots(existing_items, places_by_id)
            if act_type == "MOVE_VISIT" and item_id:
                snapshots = [s for s in snapshots if s.item_id != item_id]

            val_res = _validate_slot(
                requested_start_utc=req_start_utc,
                duration_minutes=dur_min,
                destination_timezone=dest_tz,
                place_id=place_obj.id,
                place_name=place_obj.name,
                place_latitude=place_obj.latitude,
                place_longitude=place_obj.longitude,
                place_opening_hours=place_obj.opening_hours or {},
                trip_arrival_utc=ensure_utc(trip.arrival_at) if trip.arrival_at else None,
                trip_departure_utc=ensure_utc(trip.departure_at) if trip.departure_at else None,
                existing_items=snapshots,
                transit_mode=t_mode,
                exclude_item_id=item_id if act_type == "MOVE_VISIT" else None,
                allow_duplicate_place=explicit_second_time if act_type == "ADD_VISIT" else True,
            )

            # Si le moteur de validation refuse un doublon de lieu, on renvoie un message de refus clair sans carte de confirmation
            if not val_res.valid and val_res.reason_code == "DUPLICATE_PLACE":
                reply_text = val_res.message
                proposed_action_dict = None
                action_status = "NONE"
                is_duplicate_refusal = True
            else:
                sug_dicts = [
                    SuggestedSlotSchema(**s.to_dict()).model_dump(mode="json")
                    for s in val_res.suggested_slots
                ]

                if val_res.valid:
                    if act_type == "MOVE_VISIT":
                        reply_text = (
                            f"Je vous propose de déplacer « {place_obj.name} » au "
                            f"{_format_date_fr(v_date_obj)} à {_fmt_short_time_fr(v_time_str)}. "
                            "Souhaitez-vous appliquer ce changement ?"
                        )
                    elif (
                        not reply_text
                        or re.search(r"\b20\d{2}-\d{2}-\d{2}\b", reply_text)
                        or place_obj.name.lower() not in reply_text.lower()
                    ):
                        reply_text = (
                            f"Je vous propose d'ajouter « {place_obj.name} » le "
                            f"{_format_date_fr(v_date_obj)} à {_fmt_short_time_fr(v_time_str)} ({dur_min} min). "
                            "Rien n'est modifié tant que vous ne confirmez pas."
                        )

                if not val_res.valid:
                    # Si l'horaire demandé est libre un autre jour du séjour (ex. la veille ou le lendemain),
                    # le placer en tête des propositions alternatives.
                    other_days = sorted(
                        [d for d in trip_dates if d != v_date_obj],
                        key=lambda d: (0 if (d - v_date_obj).days == -1 else 1, abs((d - v_date_obj).days), d),
                    )
                    for cand_day in other_days:
                        cand_s_utc, cand_e_utc = parse_local_slot_to_utc(
                            visit_date=cand_day,
                            local_start_time_str=v_time_str,
                            duration_minutes=dur_min,
                            timezone_name=dest_tz,
                        )
                        cand_check = _validate_slot(
                            requested_start_utc=cand_s_utc,
                            duration_minutes=dur_min,
                            destination_timezone=dest_tz,
                            place_id=place_obj.id,
                            place_name=place_obj.name,
                            place_latitude=place_obj.latitude,
                            place_longitude=place_obj.longitude,
                            place_opening_hours=place_obj.opening_hours or {},
                            trip_arrival_utc=ensure_utc(trip.arrival_at) if trip.arrival_at else None,
                            trip_departure_utc=ensure_utc(trip.departure_at) if trip.departure_at else None,
                            existing_items=snapshots,
                            transit_mode=t_mode,
                            exclude_item_id=item_id if act_type == "MOVE_VISIT" else None,
                            allow_duplicate_place=True,
                        )
                        if cand_check.valid:
                            loc_s = to_destination_local(cand_s_utc, dest_tz)
                            loc_e = to_destination_local(cand_e_utc, dest_tz)
                            same_hour_slot = SuggestedSlotSchema(
                                start_at=cand_s_utc.isoformat(),
                                end_at=cand_e_utc.isoformat(),
                                local_date=loc_s.strftime("%Y-%m-%d"),
                                local_start_time=loc_s.strftime("%H:%M"),
                                local_end_time=loc_e.strftime("%H:%M"),
                                timezone=dest_tz,
                                label=f"{_format_date_fr(cand_day)} de {loc_s.strftime('%H:%M')} à {loc_e.strftime('%H:%M')}",
                            ).model_dump(mode="json")
                            sug_dicts = [
                                same_hour_slot,
                                *[
                                    s
                                    for s in sug_dicts
                                    if not (
                                        s["local_date"] == same_hour_slot["local_date"]
                                        and s["local_start_time"] == same_hour_slot["local_start_time"]
                                    )
                                ],
                            ][:3]
                            break

                    day_cap = _FR_WEEKDAYS[v_date_obj.weekday()].capitalize()
                    req_t = _fmt_short_time_fr(v_time_str)
                    cd = val_res.conflict_details or {}

                    if val_res.reason_code == "OVERLAPPING_VISIT":
                        c_name = str(cd.get("conflicting_place_name") or "une autre visite")
                        c_s_iso = str(cd.get("conflicting_start_local") or "")
                        c_e_iso = str(cd.get("conflicting_end_local") or "")
                        c_s_hm = datetime.fromisoformat(c_s_iso).strftime("%H:%M") if c_s_iso else "09:00"
                        c_e_hm = datetime.fromisoformat(c_e_iso).strftime("%H:%M") if c_e_iso else "11:00"
                        reason_sentence = (
                            f"{day_cap} à {req_t}, vous avez déjà {c_name} "
                            f"({_fmt_short_time_fr(c_s_hm)}-{_fmt_short_time_fr(c_e_hm)})."
                        )
                    elif val_res.reason_code == "OUTSIDE_OPENING_HOURS":
                        oh = str(cd.get("opening_hours") or "")
                        if oh.lower() in ("fermé", "ferme", "closed"):
                            reason_sentence = f"{day_cap} à {req_t}, {place_obj.name} est fermé ce jour-là."
                        elif "-" in oh:
                            oh_parts = oh.split("-", 1)
                            reason_sentence = (
                                f"{day_cap} à {req_t}, {place_obj.name} est ouvert de "
                                f"{_fmt_short_time_fr(oh_parts[0])} à {_fmt_short_time_fr(oh_parts[1])}."
                            )
                        else:
                            reason_sentence = f"{day_cap} à {req_t}, {place_obj.name} est fermé sur ce créneau."
                    elif val_res.reason_code == "INSUFFICIENT_TRAVEL_TIME":
                        req_min = int(cd.get("required_travel_minutes") or 15)
                        other_p = str(
                            cd.get("from_place")
                            if cd.get("direction") == "from_previous"
                            else cd.get("to_place") or "votre autre visite"
                        )
                        reason_sentence = (
                            f"{day_cap} à {req_t}, il faut compter {req_min} min de trajet avec {other_p}."
                        )
                    else:
                        phase = str(cd.get("violation_phase") or "")
                        if phase in ("BEFORE_ARRIVAL", "ARRIVAL_BUFFER"):
                            eff_s = str(cd.get("effective_window_start_local") or "")
                            eff_hm = datetime.fromisoformat(eff_s).strftime("%H:%M") if eff_s else "11:00"
                            reason_sentence = (
                                f"{day_cap} à {req_t}, les visites commencent à partir de "
                                f"{_fmt_short_time_fr(eff_hm)} après votre arrivée."
                            )
                        else:
                            eff_e = str(cd.get("effective_window_end_local") or "")
                            eff_hm = datetime.fromisoformat(eff_e).strftime("%H:%M") if eff_e else "16:00"
                            reason_sentence = (
                                f"{day_cap} à {req_t}, les visites se terminent à "
                                f"{_fmt_short_time_fr(eff_hm)} avant votre départ."
                            )

                    if sug_dicts:
                        first_s = sug_dicts[0]
                        sug_d = date.fromisoformat(str(first_s["local_date"]))
                        sug_day_fr = _FR_WEEKDAYS[sug_d.weekday()]
                        sug_t = _fmt_short_time_fr(str(first_s["local_start_time"]))
                        reply_text = f"{reason_sentence} Je vous propose {sug_day_fr} à {sug_t}."
                    else:
                        reply_text = reason_sentence
                elif named_trip_date is not None:
                    if act_type == "MOVE_VISIT":
                        reply_text = (
                            f"Je vous propose de déplacer « {place_obj.name} » au "
                            f"{_format_date_fr(v_date_obj)} à {_fmt_short_time_fr(v_time_str)}. "
                            "Souhaitez-vous appliquer ce changement ?"
                        )
                    else:
                        reply_text = (
                            f"Je vous propose d'ajouter « {place_obj.name} » le "
                            f"{_format_date_fr(v_date_obj)} à {_fmt_short_time_fr(v_time_str)} ({dur_min} min). "
                            "Rien n'est modifié tant que vous ne confirmez pas."
                        )

                proposed_action_dict = {
                    "action_type": act_type,
                    "item_id": item_id,
                    "place_id": place_obj.id,
                    "place_name": place_obj.name,
                    "visit_date": v_date_str,
                    "local_start_time": v_time_str,
                    "local_end_time": loc_end_str,
                    "duration_minutes": dur_min,
                    "transit_mode": t_mode,
                    "allow_duplicate": explicit_second_time,
                    "validated_by_engine": val_res.valid,
                    "validation_error_code": val_res.reason_code if not val_res.valid else None,
                    "validation_message_fr": reply_text if not val_res.valid else None,
                    "suggested_slots": sug_dicts,
                }
                action_status = "PENDING_CONFIRMATION"

    # Journalisation de chaque phrase non comprise ou incomplète dans la table chat_unrecognized
    if proposed_action_dict is None and not is_info_reply and not is_duplicate_refusal:
        unrec_reason = (
            "SCHEMA_OR_PARSE_FAILURE"
            if validated_ai is None
            else (
                "MISSING_DATE_OR_TIME"
                if (validated_ai.get("place_name") or isinstance(raw_action, dict))
                else "UNRECOGNIZED_INTENT"
            )
        )
        db.add(
            ChatUnrecognized(
                trip_id=trip.id,
                user_id=current_user.id,
                raw_message=payload.message.strip(),
                reason=unrec_reason,
                assistant_reply=reply_text,
            )
        )

    assistant_msg = ChatMessage(
        trip_id=trip.id,
        sender_role="assistant",
        content=reply_text,
        proposed_action=proposed_action_dict,
        action_status=action_status,
    )
    db.add(assistant_msg)
    await db.commit()

    return await get_trip_chat_history(trip_id=trip.id, current_user=current_user, db=db)


@router.post(
    "/trip/{trip_id}/chat/{message_id}/confirm",
    response_model=ChatActionDecisionResponse,
)
async def confirm_chat_proposed_action(
    trip_id: str,
    message_id: str,
    override_visit_date: date | None = Query(default=None),
    override_local_start_time: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatActionDecisionResponse:
    """
    Exécute la modification proposée par l'assistant UNIQUEMENT après confirmation explicite
    de l'utilisateur ET validation par le moteur de validation.
    """
    registry = get_provider_registry()
    trip, destination = await _load_trip_and_destination_strict(db, trip_id, current_user.id)
    dest_tz = destination.timezone or "UTC"

    msg = await db.scalar(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.trip_id == trip.id,
        )
    )
    if not msg or not msg.proposed_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune proposition d'action en attente sur ce message.",
        )
    if msg.action_status == "CONFIRMED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette proposition a déjà été confirmée.",
        )

    action = dict(msg.proposed_action)
    act_type = str(action.get("action_type"))
    item_id = action.get("item_id")
    place_id = str(action.get("place_id"))
    dur_min = int(action.get("duration_minutes") or 90)
    t_mode = normalize_transit_mode(str(action.get("transit_mode") or "METRO"))
    allow_dup = bool(action.get("allow_duplicate", False))

    if act_type == "REMOVE_VISIT":
        if not item_id:
            raise HTTPException(status_code=422, detail="Identifiant de visite manquant pour la suppression.")
        it_obj = await db.scalar(
            select(ItineraryItem).where(ItineraryItem.id == item_id, ItineraryItem.trip_id == trip.id)
        )
        if not it_obj:
            raise HTTPException(status_code=404, detail="Visite déjà supprimée ou introuvable.")
        if it_obj.google_calendar_event_id:
            try:
                await registry.calendar.delete_visit_event(
                    calendar_id="primary",
                    event_id=it_obj.google_calendar_event_id,
                )
            except Exception:
                pass
        await db.delete(it_obj)
        msg.action_status = "CONFIRMED"
        await db.commit()
        await _recompute_trip_day_transits(db, trip.id, dest_tz)
        return ChatActionDecisionResponse(
            message=_serialize_chat_message(msg),
            applied_change=True,
            updated_item=None,
            deleted_item_id=item_id,
            detail_fr=f"Modification confirmée et appliquée : la visite « {action.get('place_name')} » a bien été retirée de votre programme.",
        )

    place = await db.scalar(
        select(Place).where(Place.id == place_id, Place.destination_id == destination.id)
    )
    if not place:
        raise HTTPException(status_code=404, detail="Lieu introuvable pour cette destination.")

    sug_list = action.get("suggested_slots") or []
    if override_visit_date is None and not action.get("validated_by_engine") and sug_list:
        v_date = date.fromisoformat(str(sug_list[0]["local_date"]))
        v_time = str(sug_list[0]["local_start_time"])
    else:
        v_date = override_visit_date or date.fromisoformat(str(action["visit_date"]))
        v_time = override_local_start_time or str(action["local_start_time"])
    req_start_utc, req_end_utc = parse_local_slot_to_utc(
        visit_date=v_date,
        local_start_time_str=v_time,
        duration_minutes=dur_min,
        timezone_name=dest_tz,
    )

    existing_items, places_map = await _load_trip_items_with_places(db, trip.id)

    # Si l'action est MOVE_VISIT (ou ADD_VISIT sans allow_duplicate sur un lieu déjà présent),
    # on résout systématiquement la visite existante afin de ne JAMAIS créer de doublon
    target_existing_item: ItineraryItem | None = None
    if item_id:
        target_existing_item = next((it for it in existing_items if it.id == str(item_id)), None)
    if target_existing_item is None and (act_type == "MOVE_VISIT" or not allow_dup):
        target_existing_item = next(
            (it for it in reversed(existing_items) if it.place_id == place.id),
            None,
        )
        if target_existing_item is not None and act_type == "MOVE_VISIT":
            item_id = target_existing_item.id

    snapshots = _build_snapshots(existing_items, places_map)
    if act_type == "MOVE_VISIT" and item_id:
        snapshots = [s for s in snapshots if s.item_id != item_id]

    val_res = _validate_slot(
        requested_start_utc=req_start_utc,
        duration_minutes=dur_min,
        destination_timezone=dest_tz,
        place_id=place.id,
        place_name=place.name,
        place_latitude=place.latitude,
        place_longitude=place.longitude,
        place_opening_hours=place.opening_hours or {},
        trip_arrival_utc=ensure_utc(trip.arrival_at) if trip.arrival_at else None,
        trip_departure_utc=ensure_utc(trip.departure_at) if trip.departure_at else None,
        existing_items=snapshots,
        transit_mode=t_mode,
        exclude_item_id=item_id if act_type == "MOVE_VISIT" else None,
        allow_duplicate_place=True if act_type == "MOVE_VISIT" else allow_dup,
    )
    if not val_res.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": val_res.reason_code,
                "message": str(action.get("validation_message_fr") or val_res.message).replace(
                    "Visite refusée : ", ""
                ),
                "suggested_slots": [
                    SuggestedSlotSchema(**s.to_dict()).model_dump(mode="json")
                    for s in val_res.suggested_slots
                ],
            },
        )

    if act_type == "MOVE_VISIT":
        if target_existing_item is None:
            raise HTTPException(status_code=404, detail="Visite à déplacer introuvable.")
        target_existing_item.visit_date = v_date
        target_existing_item.start_at = req_start_utc
        target_existing_item.end_at = req_end_utc
        target_existing_item.duration_minutes = dur_min
        target_existing_item.transit_mode_to_next = t_mode
        msg.action_status = "CONFIRMED"
        await db.commit()
        await _recompute_trip_day_transits(db, trip.id, dest_tz)
        await _sync_item_with_google_calendar(db, target_existing_item, place, dest_tz, action="update")
        return ChatActionDecisionResponse(
            message=_serialize_chat_message(msg),
            applied_change=True,
            updated_item=_to_item_response(target_existing_item, place, dest_tz),
            deleted_item_id=None,
            detail_fr=(
                f"Modification confirmée et appliquée : visite « {place.name} » "
                f"déplacée au {_format_date_fr(v_date)} à {v_time}."
            ),
        )

    new_item = ItineraryItem(
        trip_id=trip.id,
        place_id=place.id,
        visit_date=v_date,
        start_at=req_start_utc,
        end_at=req_end_utc,
        duration_minutes=dur_min,
        day_order_index=len(existing_items) + 1,
        transit_mode_to_next=t_mode,
        transit_duration_to_next_min=0,
        transit_distance_meters=0,
        transit_time_source="ESTIMATED",
        calendar_sync_status="PENDING_SYNC",
        calendar_sync_attempts=0,
        notes="Ajouté depuis l'assistant de voyage après confirmation",
    )
    db.add(new_item)
    msg.action_status = "CONFIRMED"
    await db.commit()
    await db.refresh(new_item)
    await _recompute_trip_day_transits(db, trip.id, dest_tz)
    await _sync_item_with_google_calendar(db, new_item, place, dest_tz, action="create")

    return ChatActionDecisionResponse(
        message=_serialize_chat_message(msg),
        applied_change=True,
        updated_item=_to_item_response(new_item, place, dest_tz),
        deleted_item_id=None,
        detail_fr=(
            f"Modification confirmée et appliquée : visite « {place.name} » "
            f"ajoutée le {_format_date_fr(v_date)} à {v_time}."
        ),
    )


@router.post(
    "/trip/{trip_id}/chat/{message_id}/reject",
    response_model=ChatActionDecisionResponse,
)
async def reject_chat_proposed_action(
    trip_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatActionDecisionResponse:
    """
    Refuse la proposition de l'assistant : aucune modification n'est apportée au programme.
    """
    trip, _destination = await _load_trip_and_destination_strict(db, trip_id, current_user.id)
    msg = await db.scalar(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.trip_id == trip.id,
        )
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Message introuvable.")

    msg.action_status = "REJECTED"
    await db.commit()
    await db.refresh(msg)
    return ChatActionDecisionResponse(
        message=_serialize_chat_message(msg),
        applied_change=False,
        updated_item=None,
        deleted_item_id=None,
        detail_fr="Proposition refusée : votre programme reste inchangé.",
    )
