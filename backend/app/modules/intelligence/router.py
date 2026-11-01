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
from app.core.rbac import READ_ROLES, WRITE_ROLES, require_trip_access
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
from app.modules.budget.router import build_trip_budget_summary
from app.modules.destinations.router import DESTINATION_PRACTICAL_CATALOG
from app.modules.documents.router import build_trip_documents_list
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
    VoiceCommandRequest,
    VoiceCommandResponse,
    VoiceConfirmRequest,
    VoiceConfirmResponse,
    VoiceProvidersConfigResponse,
    VoiceUndoRequest,
    VoiceUndoResponse,
    WeatherAdaptationOptionSchema,
    WeatherVisitAlertSchema,
)
from app.modules.itinerary.router import (
    _build_snapshots,
    _filter_items_for_stage_validation,
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
from app.modules.trips.stages_service import (
    ensure_trip_stages,
    get_effective_departure_mode_for_stage,
    resolve_stage_for_visit,
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
    arrival_transport_mode: str | None = None,
    departure_transport_mode: str | None = None,
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
        arrival_transport_mode=arrival_transport_mode,
        departure_transport_mode=departure_transport_mode,
    )



from app.core.rbac import READ_ROLES, WRITE_ROLES, require_trip_access


# ==============================================================================
# UTILITAIRES DE CONTRÔLE D'ACCÈS & SANITISATION ANTI-INJECTION
# ==============================================================================
async def _load_trip_and_destination_strict(
    db: AsyncSession,
    trip_id: str,
    user_id: str,
    *,
    write: bool = False,
) -> tuple[Trip, Destination]:
    """
    Contrôle d'accès strict par rôle côté backend :
    - 404 si le voyage n'existe pas ;
    - 403 si l'utilisateur n'est pas membre du voyage ou si son rôle (ex. lecteur/VIEWER)
      ne permet pas l'action demandée.
    """
    allowed = WRITE_ROLES if write else READ_ROLES
    trip, destination, _role = await require_trip_access(
        db, trip_id, user_id, allowed_roles=allowed
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


def _compute_trip_dates_local(trip: Trip, dest_tz: str, stages: list[Any] | None = None) -> list[date]:
    if stages:
        loc_arr = stages[0].arrival_date
        loc_dep = stages[-1].departure_date
        dates: list[date] = []
        cur = loc_arr
        while cur <= loc_dep and len(dates) < 60:
            dates.append(cur)
            cur += timedelta(days=1)
        if dates:
            return dates
    if trip.arrival_at and trip.departure_at:
        loc_arr = to_destination_local(ensure_utc(trip.arrival_at), dest_tz).date()
        loc_dep = to_destination_local(ensure_utc(trip.departure_at), dest_tz).date()
        dates = []
        cur = loc_arr
        while cur <= loc_dep and len(dates) < 60:
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
    trip, destination = await _load_trip_and_destination_strict(
        db, trip_id, current_user.id, write=True
    )
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
    trip, destination = await _load_trip_and_destination_strict(
        db, trip_id, current_user.id, write=True
    )
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
    trip, destination = await _load_trip_and_destination_strict(
        db, trip_id, current_user.id, write=True
    )
    dest_tz = destination.timezone or "UTC"
    trip_dates = _compute_trip_dates_local(trip, dest_tz)

    places_res = await db.scalars(
        select(Place)
        .where(Place.destination_id == destination.id)
        .order_by(Place.notoriety_score.desc(), Place.avg_rating.desc())
    )
    db_places = list(places_res.all())
    if not db_places and destination.city_name.strip().lower() not in {"tokyo", "rome", "new york", "marrakech", "paris"}:
        from app.modules.places.router import ensure_destination_world_places

        db_places, _, _ = await ensure_destination_world_places(db=db, dest=destination)
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
    trip, destination = await _load_trip_and_destination_strict(
        db, trip_id, current_user.id, write=True
    )
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
    current_user_id: str | None = None,
    user_role: str = "OWNER",
) -> tuple[dict[str, Any], dict[str, Place], list[ItineraryItem]]:
    """
    Construit le contexte du voyage pour l'assistant de chat en respectant strictement :
    1. Aucune donnée d'un autre utilisateur ni d'un autre voyage,
    2. Aucun document déchiffré du coffre-fort (VaultDocument) ni jeton OAuth Google (google_oauth_tokens),
    3. Les descriptions de lieux sont encapsulées et nettoyées comme de simples données passives.
    """
    dest_tz = destination.timezone or "UTC"
    stages = await ensure_trip_stages(db, trip)
    stage_by_id = {s.id: s for s in stages}
    stage_dest_ids = list({destination.id, *[s.destination_id for s in stages if s.destination_id]})

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
        select(Place)
        .where(Place.destination_id.in_(stage_dest_ids))
        .order_by(Place.notoriety_score.desc(), Place.avg_rating.desc())
    )
    dest_places = list(dest_places_res.all())
    if not dest_places and destination.city_name.strip().lower() not in {"tokyo", "rome", "new york", "marrakech", "paris"}:
        from app.modules.places.router import ensure_destination_world_places

        dest_places, _, _ = await ensure_destination_world_places(db=db, dest=destination)
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
        item_stage = stage_by_id.get(item.stage_id or "")
        if item_stage is None and stages:
            item_stage, _ = resolve_stage_for_visit(stages, visit_date=item.visit_date, place=p)
        item_tz = item_stage.timezone if item_stage else dest_tz
        loc_s = to_destination_local(ensure_utc(item.start_at), item_tz)
        loc_e = to_destination_local(ensure_utc(item.end_at), item_tz)
        visits_cost += float(p.estimated_cost or 0.0)
        itinerary_safe.append(
            {
                "item_id": item.id,
                "stage_id": item_stage.id if item_stage else item.stage_id,
                "stage_city_name": item_stage.city_name if item_stage else destination.city_name,
                "stage_timezone": item_tz,
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

    trip_dates = _compute_trip_dates_local(trip, dest_tz, stages=stages)
    weather_days, _, _, _ = await _fetch_trip_weather_forecasts(
        destination=destination,
        trip_dates=trip_dates,
    )

    flight_cost = float(flight_obj.price) if flight_obj else 0.0
    planned_total = float(trip.total_budget_planned or 2000.0)
    budget_dict: dict[str, Any] = {
        "planned_total": planned_total,
        "flight_cost": flight_cost,
        "visits_estimated_cost": round(visits_cost, 2),
        "remaining_estimated": round(max(0.0, planned_total - flight_cost - visits_cost), 2),
    }
    try:
        b_summary = await build_trip_budget_summary(db, trip, destination)
        cat_parts = [
            f"{c.label_fr} {float(c.spent_amount):.0f} {b_summary.currency}"
            for c in b_summary.categories
            if float(c.spent_amount) > 0
        ]
        budget_dict.update(
            {
                "planned_total": float(b_summary.total_planned),
                "total_spent": float(b_summary.total_spent),
                "committed_total": float(b_summary.total_spent),
                "remaining_total": float(b_summary.remaining),
                "remaining_estimated": float(b_summary.remaining),
                "over_budget_alert": bool(b_summary.over_budget_alert),
                "alert_message_fr": b_summary.alert_message_fr,
                "categories_summary_fr": ", ".join(cat_parts),
            }
        )
    except Exception:
        pass

    docs_summary_dict: dict[str, Any] = {
        "visible_count": 0,
        "titles": [],
        "passport_expiration_alert": False,
        "passport_alert_message_fr": None,
    }
    try:
        docs_list = await build_trip_documents_list(
            db,
            trip,
            destination,
            current_user_id or trip.owner_id,
            user_role,
        )
        docs_summary_dict = {
            "visible_count": len(docs_list.documents),
            "titles": [d.title for d in docs_list.documents],
            "passport_expiration_alert": bool(docs_list.passport_expiration_alert),
            "passport_alert_message_fr": docs_list.passport_alert_message_fr,
        }
    except Exception:
        pass

    city_key = (destination.city_name or "").strip().lower()
    p_cat = (
        DESTINATION_PRACTICAL_CATALOG.get(city_key)
        or DESTINATION_PRACTICAL_CATALOG.get(destination.city_name)
        or {}
    )
    practical_info_dict = {
        "plugs": p_cat.get("plugs") or p_cat.get("plugs_fr") or "Prises locales",
        "tipping": p_cat.get("tipping") or p_cat.get("tipping_fr") or "Variable selon le service",
        "emergency": p_cat.get("emergency") or p_cat.get("emergency_fr") or "Urgences locales",
        "dial_code": p_cat.get("dial_code") or "",
        "currency": p_cat.get("currency") or p_cat.get("currency_fr") or trip.currency or "EUR",
        "source": p_cat.get("source") or p_cat.get("source_fr") or "Conseils aux Voyageurs",
        "updated_at_fr": p_cat.get("updated_at_fr") or "15 octobre 2026",
    }

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
            "stages_count": len(stages),
        },
        "stages": [
            {
                "id": s.id,
                "order_index": s.order_index,
                "city_name": s.city_name,
                "country": s.country,
                "timezone": s.timezone,
                "arrival_date": s.arrival_date.isoformat(),
                "departure_date": s.departure_date.isoformat(),
                "nights": s.nights,
                "arrival_transport_mode": s.arrival_transport_mode,
            }
            for s in stages
        ],
        "flight": flight_data,
        "accommodation": acc_data,
        "budget": budget_dict,
        "documents_summary": docs_summary_dict,
        "practical_info": practical_info_dict,
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
    trip, destination = await _load_trip_and_destination_strict(
        db, trip_id, current_user.id, write=True
    )
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
        "AUTRE": "Autre",
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
        "navigation_target",
        "voice_command",
        "day_number",
        "requires_double_confirmation",
        "confirmation_steps_required",
        "confirmation_step",
        "spoken_summary_fr",
        "ask_reason",
        "place_similarity_score",
        "explicit_date",
        "explicit_time",
        "executed_directly",
        "undo_available",
        "undo_window_seconds",
        "undo_snapshot",
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
        "BOOK": "BOOK_RESERVATION",
        "BOOK_RESERVATION": "BOOK_RESERVATION",
        "PAY": "PROCESS_PAYMENT",
        "PROCESS_PAYMENT": "PROCESS_PAYMENT",
        "NAVIGATE": "NAVIGATE",
        "READ_DAY": "READ_DAY",
        "READ_BUDGET": "READ_BUDGET",
        "OPEN_DOCUMENTS": "OPEN_DOCUMENTS",
        "OPEN_PRACTICAL_INFO": "OPEN_PRACTICAL_INFO",
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

    if norm_act in {"INFO", "NAVIGATE", "READ_DAY", "READ_BUDGET", "OPEN_DOCUMENTS", "OPEN_PRACTICAL_INFO"}:
        return {
            "action_type": norm_act,
            "info_subtype": raw_res.get("info_subtype"),
            "voice_command": raw_res.get("voice_command"),
            "navigation_target": raw_res.get("navigation_target"),
            "day_number": raw_res.get("day_number"),
            "place_name": raw_res.get("place_name"),
            "visit_date": raw_res.get("visit_date"),
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
            "ask_reason": raw_res.get("ask_reason"),
            "place_name": raw_pname.strip() if isinstance(raw_pname, str) and raw_pname.strip() else None,
            "visit_date": norm_date,
            "local_start_time": norm_time,
            "reply": str(
                reply_val
                or "Je n'ai pas compris. Voulez-vous ajouter, déplacer ou retirer une visite ?"
            ),
            "proposed_action": None,
        }

    needs_double = norm_act in {"REMOVE_VISIT", "BOOK_RESERVATION", "PROCESS_PAYMENT"}
    raw_sim = act_src.get("place_similarity_score") if "place_similarity_score" in act_src else raw_res.get("place_similarity_score")
    norm_sim = float(raw_sim) if isinstance(raw_sim, (int, float)) else None
    raw_exp_date = act_src.get("explicit_date") if "explicit_date" in act_src else raw_res.get("explicit_date")
    raw_exp_time = act_src.get("explicit_time") if "explicit_time" in act_src else raw_res.get("explicit_time")
    return {
        "action_type": norm_act,
        "place_similarity_score": norm_sim,
        "explicit_date": bool(raw_exp_date),
        "explicit_time": bool(raw_exp_time),
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
            "requires_double_confirmation": needs_double,
            "confirmation_steps_required": 2 if needs_double else 1,
            "confirmation_step": 1,
            "place_similarity_score": norm_sim,
            "explicit_date": bool(raw_exp_date),
            "explicit_time": bool(raw_exp_time),
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
    trip, destination = await _load_trip_and_destination_strict(
        db, trip_id, current_user.id, write=True
    )
    dest_tz = destination.timezone or "UTC"
    stages = await ensure_trip_stages(db, trip)
    stage_by_id = {s.id: s for s in stages}

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
        last_item_stage = stage_by_id.get(last_item.stage_id or "")
        last_tz = last_item_stage.timezone if last_item_stage else dest_tz
        loc_last = to_destination_local(ensure_utc(last_item.start_at), last_tz)
        last_context_date = loc_last.strftime("%Y-%m-%d")
        last_context_time = loc_last.strftime("%H:%M")

    if last_context_place is not None:
        # Toujours recalculer la date/heure réelle si le lieu est déjà au programme
        sched_for_last = next(
            (it for it in reversed(existing_items) if it.place_id == last_context_place.id),
            None,
        )
        if sched_for_last is not None:
            sched_stage = stage_by_id.get(sched_for_last.stage_id or "")
            sched_tz = sched_stage.timezone if sched_stage else dest_tz
            loc_sched = to_destination_local(ensure_utc(sched_for_last.start_at), sched_tz)
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

    trip_dates = _compute_trip_dates_local(trip, dest_tz, stages=stages)


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

    def _has_pronoun_ref_in_msg(raw_msg: str) -> bool:
        m_low = raw_msg.strip().lower()
        m_norm = _norm_txt_local(raw_msg)
        stopwords_p = {
            "le", "la", "les", "l", "de", "du", "des", "d", "au", "aux", "en", "et", "a",
            "un", "une", "sur", "dans", "pour", "par", "chez", "mon", "ma", "mes", "ton",
            "ta", "tes", "son", "sa", "ses", "notre", "votre", "leur", "el", "al", "ou",
        }
        loc_quals_p = {
            "medina", "marrakech", "maroc", "gueliz", "hivernage", "kasbah", "mellah",
            "mouassine", "aguedal", "palmeraie", "paris", "france", "rome", "italie",
            "tokyo", "japon", "new", "york",
        }
        non_place_p = {
            "ajouter", "ajoute", "ajoutes", "rajouter", "rajoute", "rajoutes", "mettre",
            "mets", "met", "planifier", "planifie", "programmer", "programme", "inserer",
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
            "aimerais", "souhaite", "stp", "svp", "plait", "please", "merci", "bonjour", "salut", "fois",
            "deuxieme", "seconde", "encore", "autre",
        }
        core_toks = [
            t for t in m_norm.split()
            if t and not t.isdigit() and not re.match(r"^\d+h\d*$", t)
            and t not in stopwords_p and t not in loc_quals_p and t not in non_place_p
            and len(t) >= 3
        ]
        wants_second = bool(
            re.search(r"(deuxi[èe]me\s+fois|seconde\s+fois|une\s+autre\s+fois|encore\s+une\s+fois)", m_low)
        )
        raw_pron = bool(
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
                m_low,
            )
        )
        return bool(raw_pron and (not core_toks or wants_second))

    def _score_place_text_similarity(cand_name: str, query_text: str) -> float:
        p_norm = _norm_txt_local(cand_name)
        q_norm = _norm_txt_local(query_text)
        if not p_norm or not q_norm:
            return 0.0
        stopwords = {
            "le", "la", "les", "l", "de", "du", "des", "d", "au", "aux", "en", "et", "a",
            "un", "une", "sur", "dans", "pour", "par", "chez", "el", "al", "ou",
        }
        loc_quals = {
            "medina", "marrakech", "maroc", "gueliz", "hivernage", "kasbah", "mellah",
            "mouassine", "aguedal", "palmeraie", "paris", "france", "rome", "italie",
            "tokyo", "japon", "new", "york", "lisbonne", "lisboa", "portugal", "monastir",
            "tunisie", "milan", "milano",
        }
        for tok in _norm_txt_local(destination.city_name).split():
            if len(tok) >= 3:
                loc_quals.add(tok)
        heads = {
            "palais", "jardin", "jardins", "musee", "museum", "place", "mosquee", "parc",
            "cafe", "restaurant", "tour", "quartier", "galerie", "cathedrale", "basilique",
            "chateau", "temple", "sanctuaire", "memorial", "pont", "marche", "hotel",
            "maison", "fondation", "centre", "opera", "theatre", "tombeaux", "medersa",
            "riad", "fontaine", "statue", "monastere", "mosteiro", "castelo", "torre",
        }
        main_part = re.split(r"[\(\&]", cand_name)[0].strip()
        p_main_norm = _norm_txt_local(main_part) or p_norm
        p_space = _spaceless_local(cand_name)
        p_main_space = _spaceless_local(main_part) or p_space
        q_space = _spaceless_local(query_text)

        p_core = [t for t in p_norm.split() if t not in stopwords and len(t) >= 2]
        p_main_core = [
            t for t in p_main_norm.split() if t not in stopwords and t not in loc_quals and len(t) >= 2
        ] or list(p_core)
        p_spec = [
            t for t in p_core if t not in heads and t not in loc_quals and len(t) >= 3
        ]
        if "metropolitan" in p_core and "met" not in p_spec:
            p_spec.append("met")
        if not p_spec:
            p_spec = [t for t in p_core if t not in heads and len(t) >= 3] or list(p_main_core)
        for i in range(len(p_core) - 1):
            comp = p_core[i] + p_core[i + 1]
            if len(comp) >= 5 and comp not in p_spec:
                p_spec.append(comp)

        if p_norm in q_norm or q_norm in p_norm:
            return 1.0
        if len(p_main_norm) >= 5 and (p_main_norm in q_norm or q_norm in p_main_norm):
            return 0.99
        p_main_core_str = " ".join(p_main_core)
        q_core_toks = [
            t for t in q_norm.split()
            if len(t) >= 3 and not t.isdigit() and not re.match(r"^\d+h\d*$", t)
            and t not in stopwords and t not in loc_quals
        ]
        q_core_str = " ".join(q_core_toks)
        if len(p_main_core_str) >= 5 and p_main_core_str in q_core_str:
            return 0.97
        if len(p_space) >= 6 and (p_space in q_space or q_space in p_space):
            return 0.96
        if len(p_main_space) >= 6 and (p_main_space in q_space or q_space in p_main_space):
            return 0.95

        sc = 0.0
        for sp in p_spec:
            if sp in q_core_toks or sp in q_norm.split():
                matched_main = sum(
                    1 for ct in p_main_core if any(SequenceMatcher(None, ct, qt).ratio() >= 0.80 for qt in q_norm.split())
                )
                sc = max(sc, 0.86 + 0.04 * matched_main)
            elif len(sp) >= 4 and q_core_toks:
                best_r = max((SequenceMatcher(None, sp, qt).ratio() for qt in q_core_toks), default=0.0)
                if best_r >= 0.76:
                    matched_main = sum(
                        1 for ct in p_main_core if any(SequenceMatcher(None, ct, qt).ratio() >= 0.75 for qt in q_norm.split())
                    )
                    sc = max(sc, 0.78 * best_r + 0.05 * matched_main)
        return sc

    def _resolve_place_obj(raw_action_dict: dict[str, Any], raw_msg: str) -> Place | None:
        MIN_SIM_THRESHOLD = 0.65
        pid = str(raw_action_dict.get("place_id") or "").strip()
        if pid and pid in places_by_id:
            return places_by_id[pid]

        pname = str(raw_action_dict.get("place_name") or "").strip()
        if pname:
            pname_low = pname.lower()
            pname_norm = _norm_txt_local(pname)
            for p in places_by_id.values():
                if p.name.lower() == pname_low or _norm_txt_local(p.name) == pname_norm:
                    return p
            best_by_name: Place | None = None
            best_name_sc = 0.0
            for p in places_by_id.values():
                sc = _score_place_text_similarity(p.name, pname)
                if sc >= MIN_SIM_THRESHOLD and sc > best_name_sc:
                    best_name_sc = sc
                    best_by_name = p
            if best_by_name is not None:
                return best_by_name

        iid = str(raw_action_dict.get("item_id") or "").strip()
        if iid:
            for it in existing_items:
                if it.id == iid and it.place_id in places_by_id:
                    return places_by_id[it.place_id]

        scored_from_msg: list[tuple[Place, float]] = [
            (p, _score_place_text_similarity(p.name, raw_msg))
            for p in places_by_id.values()
        ]
        scored_from_msg.sort(key=lambda item: -round(item[1], 3))
        if scored_from_msg and scored_from_msg[0][1] >= MIN_SIM_THRESHOLD:
            if len(scored_from_msg) >= 2 and (scored_from_msg[0][1] - scored_from_msg[1][1]) < 0.12:
                return None
            return scored_from_msg[0][0]

        if last_context_place is not None and _has_pronoun_ref_in_msg(raw_msg):
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
        if (
            cand_hyb.get("action_type")
            in {
                "ADD_VISIT",
                "MOVE_VISIT",
                "REMOVE_VISIT",
                "BOOK_RESERVATION",
                "PROCESS_PAYMENT",
                "NAVIGATE",
                "READ_DAY",
                "READ_BUDGET",
                "OPEN_DOCUMENTS",
                "OPEN_PRACTICAL_INFO",
                "INFO",
            }
            or raw_rules_hyb.get("ask_reason") in {"AMBIGUOUS_PLACE", "UNKNOWN_PLACE"}
            or provider_mode != "real"
        ):
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

    # Point 1 : Question d'information (autres lieux, horaires, météo, budget) ou commande vocale de navigation/lecture -> sans modification
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
    elif validated_ai is not None and validated_ai.get("action_type") in {
        "INFO",
        "NAVIGATE",
        "READ_DAY",
        "READ_BUDGET",
        "OPEN_DOCUMENTS",
        "OPEN_PRACTICAL_INFO",
    }:
        if validated_ai.get("action_type") == "INFO" and validated_ai.get("info_subtype") == "PLACES":
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
        "BOOK_RESERVATION",
        "PROCESS_PAYMENT",
    }:
        act_type = str(raw_action["action_type"])
        v_date_str = (
            named_trip_date.isoformat()
            if named_trip_date is not None
            else str(raw_action.get("visit_date") or trip_dates[0].isoformat())
        )
        v_time_str = str(msg_extracted_time or raw_action.get("local_start_time") or "10:00")
        dur_min = int(raw_action.get("duration_minutes") or 60)
        t_mode = normalize_transit_mode(str(raw_action.get("transit_mode") or "METRO"))
        proposed_action_dict = {
            "action_type": act_type,
            "item_id": None,
            "place_id": str(raw_action.get("place_id") or f"voice-{act_type.lower()}"),
            "place_name": str(raw_action.get("place_name") or ("Réservation" if act_type == "BOOK_RESERVATION" else "Paiement")),
            "visit_date": v_date_str,
            "local_start_time": v_time_str,
            "local_end_time": None,
            "duration_minutes": dur_min,
            "transit_mode": t_mode,
            "allow_duplicate": False,
            "validated_by_engine": True,
            "validation_error_code": None,
            "validation_message_fr": None,
            "suggested_slots": [],
            "requires_double_confirmation": True,
            "confirmation_steps_required": 2,
            "confirmation_step": 1,
            "spoken_summary_fr": reply_text,
        }
        action_status = "PENDING_CONFIRMATION"
    elif isinstance(raw_action, dict) and raw_action.get("action_type") in {
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
                m_stage = stage_by_id.get(matching_existing_item.stage_id or "")
                m_tz = m_stage.timezone if m_stage else dest_tz
                v_date_str = to_destination_local(
                    ensure_utc(matching_existing_item.start_at), m_tz
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
            m_stage = stage_by_id.get(matching_existing_item.stage_id or "")
            m_tz = m_stage.timezone if m_stage else dest_tz
            v_date_str = to_destination_local(
                ensure_utc(matching_existing_item.start_at), m_tz
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

        if place_obj is None:
            proposed_action_dict = None
            action_status = "NONE"
            if "?" not in reply_text:
                reply_text = f"Je ne trouve pas ce lieu à {destination.city_name}. De quel lieu parlez-vous ?"
        elif act_type == "REMOVE_VISIT" and v_date_str is not None:
            rem_date_obj = date.fromisoformat(v_date_str)
            rem_stage, _ = resolve_stage_for_visit(
                stages,
                visit_date=rem_date_obj,
                local_start_time=v_time_str,
                duration_minutes=dur_min,
                place=place_obj,
            )
            proposed_action_dict = {
                "action_type": "REMOVE_VISIT",
                "item_id": item_id,
                "stage_id": rem_stage.id if rem_stage else None,
                "stage_order_index": rem_stage.order_index if rem_stage else None,
                "stage_city_name": rem_stage.city_name if rem_stage else destination.city_name,
                "stage_timezone": rem_stage.timezone if rem_stage else dest_tz,
                "place_id": place_id,
                "place_name": place_obj.name,
                "visit_date": v_date_str,
                "local_start_time": v_time_str,
                "local_end_time": None,
                "duration_minutes": dur_min,
                "transit_mode": t_mode,
                "validated_by_engine": True,
                "validation_error_code": None,
                "validation_message_fr": None,
                "suggested_slots": [],
                "requires_double_confirmation": True,
                "confirmation_steps_required": 2,
                "confirmation_step": 1,
                "spoken_summary_fr": reply_text,
            }
            action_status = "PENDING_CONFIRMATION"
        elif place_obj is not None and v_date_str is not None:
            v_date_obj = date.fromisoformat(v_date_str)
            target_stage, target_stage_idx = resolve_stage_for_visit(
                stages,
                visit_date=v_date_obj,
                local_start_time=v_time_str,
                duration_minutes=dur_min,
                place=place_obj,
            )
            stage_tz = target_stage.timezone if target_stage else dest_tz
            stage_arr_utc = (
                ensure_utc(target_stage.arrival_at)
                if target_stage
                else (ensure_utc(trip.arrival_at) if trip.arrival_at else None)
            )
            stage_dep_utc = (
                ensure_utc(target_stage.departure_at)
                if target_stage
                else (ensure_utc(trip.departure_at) if trip.departure_at else None)
            )
            stage_arr_mode = target_stage.arrival_transport_mode if target_stage else None
            stage_dep_mode = (
                get_effective_departure_mode_for_stage(stages, target_stage_idx)
                if target_stage
                else None
            )

            req_start_utc, req_end_utc = parse_local_slot_to_utc(
                visit_date=v_date_obj,
                local_start_time_str=v_time_str,
                duration_minutes=dur_min,
                timezone_name=stage_tz,
            )
            loc_end_str = to_destination_local(req_end_utc, stage_tz).strftime("%H:%M")
            stage_items = _filter_items_for_stage_validation(existing_items, target_stage, stages)
            snapshots = _build_snapshots(stage_items, places_by_id, stage_tz)
            if act_type == "MOVE_VISIT" and item_id:
                snapshots = [s for s in snapshots if s.item_id != item_id]

            val_res = _validate_slot(
                requested_start_utc=req_start_utc,
                duration_minutes=dur_min,
                destination_timezone=stage_tz,
                place_id=place_obj.id,
                place_name=place_obj.name,
                place_latitude=place_obj.latitude,
                place_longitude=place_obj.longitude,
                place_opening_hours=place_obj.opening_hours or {},
                trip_arrival_utc=stage_arr_utc,
                trip_departure_utc=stage_dep_utc,
                existing_items=snapshots,
                transit_mode=t_mode,
                exclude_item_id=item_id if act_type == "MOVE_VISIT" else None,
                allow_duplicate_place=explicit_second_time if act_type == "ADD_VISIT" else True,
                arrival_transport_mode=stage_arr_mode,
                departure_transport_mode=stage_dep_mode,
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
                    # Si l'horaire demandé est libre un autre jour de la même étape (ex. la veille ou le lendemain),
                    # le placer en tête des propositions alternatives.
                    candidate_pool = (
                        [
                            d
                            for d in trip_dates
                            if d != v_date_obj
                            and target_stage.arrival_date <= d <= target_stage.departure_date
                        ]
                        if target_stage is not None
                        else [d for d in trip_dates if d != v_date_obj]
                    )
                    other_days = sorted(
                        candidate_pool,
                        key=lambda d: (0 if (d - v_date_obj).days == -1 else 1, abs((d - v_date_obj).days), d),
                    )
                    for cand_day in other_days:
                        cand_s_utc, cand_e_utc = parse_local_slot_to_utc(
                            visit_date=cand_day,
                            local_start_time_str=v_time_str,
                            duration_minutes=dur_min,
                            timezone_name=stage_tz,
                        )
                        cand_check = _validate_slot(
                            requested_start_utc=cand_s_utc,
                            duration_minutes=dur_min,
                            destination_timezone=stage_tz,
                            place_id=place_obj.id,
                            place_name=place_obj.name,
                            place_latitude=place_obj.latitude,
                            place_longitude=place_obj.longitude,
                            place_opening_hours=place_obj.opening_hours or {},
                            trip_arrival_utc=stage_arr_utc,
                            trip_departure_utc=stage_dep_utc,
                            existing_items=snapshots,
                            transit_mode=t_mode,
                            exclude_item_id=item_id if act_type == "MOVE_VISIT" else None,
                            allow_duplicate_place=True,
                            arrival_transport_mode=stage_arr_mode,
                            departure_transport_mode=stage_dep_mode,
                        )
                        if cand_check.valid:
                            loc_s = to_destination_local(cand_s_utc, stage_tz)
                            loc_e = to_destination_local(cand_e_utc, stage_tz)
                            same_hour_slot = SuggestedSlotSchema(
                                start_at=cand_s_utc.isoformat(),
                                end_at=cand_e_utc.isoformat(),
                                local_date=loc_s.strftime("%Y-%m-%d"),
                                local_start_time=loc_s.strftime("%H:%M"),
                                local_end_time=loc_e.strftime("%H:%M"),
                                timezone=stage_tz,
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

                raw_sim_val = raw_action.get("place_similarity_score") if isinstance(raw_action, dict) else None
                computed_sim = round(_score_place_text_similarity(place_obj.name, payload.message), 3)
                place_sim_score = (
                    float(raw_sim_val)
                    if isinstance(raw_sim_val, (int, float))
                    else max(computed_sim, 0.85 if _has_pronoun_ref_in_msg(payload.message) else computed_sim)
                )
                has_explicit_date = bool(
                    named_trip_date is not None
                    or (isinstance(raw_action, dict) and raw_action.get("explicit_date"))
                )
                has_explicit_time = bool(
                    msg_extracted_time is not None
                    or (isinstance(raw_action, dict) and raw_action.get("explicit_time"))
                )

                proposed_action_dict = {
                    "action_type": act_type,
                    "item_id": item_id,
                    "stage_id": target_stage.id if target_stage else None,
                    "stage_order_index": target_stage.order_index if target_stage else None,
                    "stage_city_name": target_stage.city_name if target_stage else destination.city_name,
                    "stage_timezone": stage_tz,
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
                    "requires_double_confirmation": False,
                    "confirmation_steps_required": 1,
                    "confirmation_step": 1,
                    "spoken_summary_fr": reply_text,
                    "place_similarity_score": place_sim_score,
                    "explicit_date": has_explicit_date,
                    "explicit_time": has_explicit_time,
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

    conv_res = await get_trip_chat_history(trip_id=trip.id, current_user=current_user, db=db)
    if conv_res.messages and validated_ai is not None:
        if validated_ai.get("navigation_target"):
            conv_res.messages[-1].navigation_target = str(validated_ai["navigation_target"])
        if validated_ai.get("voice_command"):
            conv_res.messages[-1].voice_command = str(validated_ai["voice_command"])
    return conv_res


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
    trip, destination = await _load_trip_and_destination_strict(
        db, trip_id, current_user.id, write=True
    )
    dest_tz = destination.timezone or "UTC"
    stages = await ensure_trip_stages(db, trip)
    stage_dest_ids = list({destination.id, *[s.destination_id for s in stages if s.destination_id]})

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

    if act_type in {"BOOK_RESERVATION", "PROCESS_PAYMENT"}:
        msg.action_status = "CONFIRMED"
        await db.commit()
        await db.refresh(msg)
        label_fr = "La réservation" if act_type == "BOOK_RESERVATION" else "Le paiement"
        return ChatActionDecisionResponse(
            message=_serialize_chat_message(msg),
            applied_change=True,
            updated_item=None,
            deleted_item_id=None,
            detail_fr=f"Modification confirmée et appliquée : {label_fr} « {action.get('place_name')} » a bien été validé(e).",
        )

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
        await _recompute_trip_day_transits(db, trip.id, dest_tz, stages=stages)
        return ChatActionDecisionResponse(
            message=_serialize_chat_message(msg),
            applied_change=True,
            updated_item=None,
            deleted_item_id=item_id,
            detail_fr=f"Modification confirmée et appliquée : la visite « {action.get('place_name')} » a bien été retirée de votre programme.",
        )

    place = await db.scalar(
        select(Place).where(Place.id == place_id, Place.destination_id.in_(stage_dest_ids))
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

    target_stage, target_stage_idx = resolve_stage_for_visit(
        stages,
        visit_date=v_date,
        local_start_time=v_time,
        duration_minutes=dur_min,
        place=place,
        explicit_stage_id=str(action["stage_id"]) if (override_visit_date is None and action.get("stage_id")) else None,
    )
    stage_tz = target_stage.timezone if target_stage else dest_tz
    stage_arr_utc = (
        ensure_utc(target_stage.arrival_at)
        if target_stage
        else (ensure_utc(trip.arrival_at) if trip.arrival_at else None)
    )
    stage_dep_utc = (
        ensure_utc(target_stage.departure_at)
        if target_stage
        else (ensure_utc(trip.departure_at) if trip.departure_at else None)
    )
    stage_arr_mode = target_stage.arrival_transport_mode if target_stage else None
    stage_dep_mode = (
        get_effective_departure_mode_for_stage(stages, target_stage_idx)
        if target_stage
        else None
    )

    req_start_utc, req_end_utc = parse_local_slot_to_utc(
        visit_date=v_date,
        local_start_time_str=v_time,
        duration_minutes=dur_min,
        timezone_name=stage_tz,
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

    stage_items = _filter_items_for_stage_validation(existing_items, target_stage, stages)
    snapshots = _build_snapshots(stage_items, places_map, stage_tz)
    if act_type == "MOVE_VISIT" and item_id:
        snapshots = [s for s in snapshots if s.item_id != item_id]

    val_res = _validate_slot(
        requested_start_utc=req_start_utc,
        duration_minutes=dur_min,
        destination_timezone=stage_tz,
        place_id=place.id,
        place_name=place.name,
        place_latitude=place.latitude,
        place_longitude=place.longitude,
        place_opening_hours=place.opening_hours or {},
        trip_arrival_utc=stage_arr_utc,
        trip_departure_utc=stage_dep_utc,
        existing_items=snapshots,
        transit_mode=t_mode,
        exclude_item_id=item_id if act_type == "MOVE_VISIT" else None,
        allow_duplicate_place=True if act_type == "MOVE_VISIT" else allow_dup,
        arrival_transport_mode=stage_arr_mode,
        departure_transport_mode=stage_dep_mode,
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
        if target_stage is not None:
            target_existing_item.stage_id = target_stage.id
        target_existing_item.visit_date = v_date
        target_existing_item.start_at = req_start_utc
        target_existing_item.end_at = req_end_utc
        target_existing_item.duration_minutes = dur_min
        target_existing_item.transit_mode_to_next = t_mode
        msg.action_status = "CONFIRMED"
        await db.commit()
        await _recompute_trip_day_transits(db, trip.id, dest_tz, stages=stages)
        await _sync_item_with_google_calendar(db, target_existing_item, place, stage_tz, action="update")
        return ChatActionDecisionResponse(
            message=_serialize_chat_message(msg),
            applied_change=True,
            updated_item=_to_item_response(target_existing_item, place, stage_tz, stage=target_stage),
            deleted_item_id=None,
            detail_fr=(
                f"Modification confirmée et appliquée : visite « {place.name} » "
                f"déplacée au {_format_date_fr(v_date)} à {v_time}."
            ),
        )

    new_item = ItineraryItem(
        trip_id=trip.id,
        stage_id=target_stage.id if target_stage is not None else None,
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
    await _recompute_trip_day_transits(db, trip.id, dest_tz, stages=stages)
    await _sync_item_with_google_calendar(db, new_item, place, stage_tz, action="create")

    return ChatActionDecisionResponse(
        message=_serialize_chat_message(msg),
        applied_change=True,
        updated_item=_to_item_response(new_item, place, stage_tz, stage=target_stage),
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
    trip, _destination = await _load_trip_and_destination_strict(
        db, trip_id, current_user.id, write=True
    )
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


# ==============================================================================
# 4. ÉTAPE 5V — ACCESSIBILITÉ VOCALE (WEB SPEECH API / WHISPER LOCAL, CONFIRMATION VOCALE)
# ==============================================================================
@router.get("/voice/providers", response_model=VoiceProvidersConfigResponse)
async def get_voice_providers_config(
    current_user: User = Depends(get_current_user),
) -> VoiceProvidersConfigResponse:
    """
    Retourne le fournisseur de reconnaissance vocale actif (Web Speech API fr-FR par défaut)
    ainsi que l'alternative Whisper local derrière la même interface BaseVoiceSTTProvider,
    avec le message de confidentialité associé.
    """
    _ = current_user
    registry = get_provider_registry()
    info = registry.voice_stt_info()
    return VoiceProvidersConfigResponse(
        active_provider=dict(info["active_provider"]),
        available_providers=[dict(p) for p in info["available_providers"]],
        supported_tts_rates=[0.8, 1.0, 1.2, 1.5],
        default_language="fr-FR",
        language="fr-FR",
        hands_free_privacy_notice_fr=(
            "En mode mains libres avec Web Speech API, l'audio peut transiter par le service de reconnaissance "
            "du navigateur. Vous pouvez sélectionner Whisper local pour un traitement hors navigateur."
        ),
    )


async def _execute_voice_undo_for_trip(
    *,
    db: AsyncSession,
    trip: Trip,
    destination: Destination,
    message_id: str | None = None,
    source: str = "VOICE",
) -> VoiceUndoResponse:
    dest_tz = destination.timezone or "UTC"
    registry = get_provider_registry()

    if message_id:
        target_msg = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.id == message_id,
                ChatMessage.trip_id == trip.id,
            )
        )
    else:
        recent_msgs_res = await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.trip_id == trip.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(20)
        )
        target_msg = None
        for cand in recent_msgs_res.all():
            if cand.action_status == "EXECUTED_DIRECTLY" and isinstance(cand.proposed_action, dict):
                snap = cand.proposed_action.get("undo_snapshot")
                if isinstance(snap, dict) and not snap.get("undone"):
                    target_msg = cand
                    break

    if not target_msg or not isinstance(target_msg.proposed_action, dict):
        msg_no_undo = "Aucune modification directe récente à annuler dans le délai de 30 secondes."
        return VoiceUndoResponse(
            ok=False,
            status="NO_RECENT_MODIFICATION",
            trip_id=trip.id,
            message_id=message_id,
            restored=False,
            operation_undone=None,
            spoken_reply_fr=msg_no_undo,
            detail_fr=msg_no_undo,
            restored_item=None,
            deleted_item_id=None,
            calendar_sync_restored=False,
            last_modification_history=None,
            message=None,
        )

    prop_dict = dict(target_msg.proposed_action)
    snap = dict(prop_dict.get("undo_snapshot") or {})
    if not snap or snap.get("undone"):
        msg_already = "Cette modification a déjà été annulée."
        return VoiceUndoResponse(
            ok=False,
            status="ALREADY_UNDONE",
            trip_id=trip.id,
            message_id=target_msg.id,
            restored=False,
            operation_undone=None,
            spoken_reply_fr=msg_already,
            detail_fr=msg_already,
            restored_item=None,
            deleted_item_id=None,
            calendar_sync_restored=False,
            last_modification_history=snap or None,
            message=_serialize_chat_message(target_msg),
        )

    executed_epoch = float(snap.get("executed_at_epoch") or 0.0)
    if executed_epoch > 0 and (time.time() - executed_epoch) > 35.0:
        msg_exp = "Le délai de 30 secondes pour annuler cette modification est écoulé."
        return VoiceUndoResponse(
            ok=False,
            status="UNDO_WINDOW_EXPIRED",
            trip_id=trip.id,
            message_id=target_msg.id,
            restored=False,
            operation_undone=str(snap.get("action_type") or ""),
            spoken_reply_fr=msg_exp,
            detail_fr=msg_exp,
            restored_item=None,
            deleted_item_id=None,
            calendar_sync_restored=False,
            last_modification_history=snap,
            message=_serialize_chat_message(target_msg),
        )

    op_type = str(snap.get("action_type") or prop_dict.get("action_type") or "")
    place_name = str(snap.get("place_name") or prop_dict.get("place_name") or "la visite")
    item_id = str(snap.get("item_id") or prop_dict.get("item_id") or "")

    restored_item_resp = None
    deleted_id: str | None = None

    if op_type == "ADD_VISIT":
        it_obj = await db.scalar(
            select(ItineraryItem).where(
                ItineraryItem.id == item_id,
                ItineraryItem.trip_id == trip.id,
            )
        )
        if it_obj is not None:
            if it_obj.google_calendar_event_id:
                try:
                    await registry.calendar.delete_visit_event(
                        calendar_id="primary",
                        event_id=it_obj.google_calendar_event_id,
                    )
                except Exception:
                    pass
            deleted_id = it_obj.id
            await db.delete(it_obj)
        snap["undone"] = True
        snap["undone_at_iso"] = datetime.now().isoformat()
        snap["undone_by"] = source
        prop_dict["undo_available"] = False
        prop_dict["undo_snapshot"] = snap
        target_msg.proposed_action = prop_dict
        target_msg.action_status = "UNDONE"
        spoken_undo = (
            f"Modification annulée : l'ajout de « {place_name} » a été retiré et votre programme ainsi que "
            "la synchronisation agenda ont été restaurés à leur état précédent."
        )
        undo_chat_msg = ChatMessage(
            trip_id=trip.id,
            sender_role="assistant",
            content=spoken_undo,
            proposed_action=None,
            action_status="UNDONE",
        )
        db.add(undo_chat_msg)
        await db.commit()
        await _recompute_trip_day_transits(db, trip.id, dest_tz)
        await db.refresh(target_msg)
        return VoiceUndoResponse(
            ok=True,
            status="UNDONE",
            trip_id=trip.id,
            message_id=target_msg.id,
            restored=True,
            operation_undone="ADD_VISIT",
            spoken_reply_fr=spoken_undo,
            detail_fr=spoken_undo,
            restored_item=None,
            deleted_item_id=deleted_id,
            calendar_sync_restored=True,
            last_modification_history=snap,
            message=_serialize_chat_message(target_msg),
        )

    # MOVE_VISIT : restauration de la date, de l'horaire, du trajet et de l'agenda
    it_obj = await db.scalar(
        select(ItineraryItem).where(
            ItineraryItem.id == item_id,
            ItineraryItem.trip_id == trip.id,
        )
    )
    if it_obj is None:
        raise HTTPException(status_code=404, detail="Visite à restaurer introuvable.")

    place_obj = await db.scalar(
        select(Place).where(Place.id == it_obj.place_id)
    )
    prev_visit_date = date.fromisoformat(str(snap["previous_visit_date"]))
    prev_start_utc = ensure_utc(datetime.fromisoformat(str(snap["previous_start_at_utc"])))
    prev_end_utc = ensure_utc(datetime.fromisoformat(str(snap["previous_end_at_utc"])))
    prev_dur = int(snap.get("previous_duration_minutes") or it_obj.duration_minutes)
    prev_tmode = normalize_transit_mode(str(snap.get("previous_transit_mode") or it_obj.transit_mode_to_next))
    prev_local_time = str(snap.get("previous_local_start_time") or "")

    it_obj.visit_date = prev_visit_date
    it_obj.start_at = prev_start_utc
    it_obj.end_at = prev_end_utc
    it_obj.duration_minutes = prev_dur
    it_obj.transit_mode_to_next = prev_tmode

    snap["undone"] = True
    snap["undone_at_iso"] = datetime.now().isoformat()
    snap["undone_by"] = source
    prop_dict["undo_available"] = False
    prop_dict["undo_snapshot"] = snap
    target_msg.proposed_action = prop_dict
    target_msg.action_status = "UNDONE"

    spoken_undo = (
        f"Modification annulée : « {place_name} » a été remis au {_format_date_fr(prev_visit_date)} "
        f"à {prev_local_time} et la synchronisation agenda a été restaurée."
    )
    undo_chat_msg = ChatMessage(
        trip_id=trip.id,
        sender_role="assistant",
        content=spoken_undo,
        proposed_action=None,
        action_status="UNDONE",
    )
    db.add(undo_chat_msg)
    await db.commit()
    await _recompute_trip_day_transits(db, trip.id, dest_tz)
    if place_obj is not None:
        await _sync_item_with_google_calendar(db, it_obj, place_obj, dest_tz, action="update")
        restored_item_resp = _to_item_response(it_obj, place_obj, dest_tz)
    await db.refresh(target_msg)

    return VoiceUndoResponse(
        ok=True,
        status="UNDONE",
        trip_id=trip.id,
        message_id=target_msg.id,
        restored=True,
        operation_undone="MOVE_VISIT",
        spoken_reply_fr=spoken_undo,
        detail_fr=spoken_undo,
        restored_item=restored_item_resp,
        deleted_item_id=None,
        calendar_sync_restored=True,
        last_modification_history=snap,
        message=_serialize_chat_message(target_msg),
    )


@router.post("/trip/{trip_id}/voice/undo", response_model=VoiceUndoResponse)
async def undo_last_voice_direct_modification(
    trip_id: str,
    payload: VoiceUndoRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VoiceUndoResponse:
    """
    Restaure l'état précédent (visite, horaire, trajets, synchronisation agenda)
    suite à une exécution vocale directe dans le délai de 30 secondes.
    """
    trip, destination, _role = await require_trip_access(
        db,
        trip_id,
        current_user.id,
        allowed_roles=WRITE_ROLES,
    )
    req = payload or VoiceUndoRequest()
    return await _execute_voice_undo_for_trip(
        db=db,
        trip=trip,
        destination=destination,
        message_id=req.message_id,
        source=req.source,
    )


@router.post("/trip/{trip_id}/voice/command", response_model=VoiceCommandResponse)
async def process_trip_voice_command(
    trip_id: str,
    payload: VoiceCommandRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VoiceCommandResponse:
    """
    Traite une commande vocale (ou un signal d'erreur micro/navigateur/silence/bruit)
    via le même analyseur que le chat et le même contrôle d'accès (cookie HttpOnly, CSRF, RBAC).
    """
    trip, destination, user_role = await require_trip_access(
        db,
        trip_id,
        current_user.id,
        allowed_roles=READ_ROLES,
    )

    registry = get_provider_registry()
    stt_provider = registry.resolve_voice_stt_provider(payload.provider)
    stt_res = await stt_provider.transcribe(
        transcript_text=payload.transcript,
        audio_base64=payload.audio_base64,
        signal=payload.signal,
        confidence=payload.confidence,
    )

    if not stt_res["ok"]:
        raw_err_code = str(stt_res.get("error_code") or payload.signal)
        err_code = "NOISE_DETECTED" if raw_err_code == "NOISE" else raw_err_code
        msg_fr = str(stt_res.get("message_fr") or "Pouvez-vous répéter ?")
        if err_code in {"UNRECOGNIZED_SPEECH", "LOW_CONFIDENCE"} and (payload.transcript or "").strip():
            db.add(
                ChatUnrecognized(
                    trip_id=trip.id,
                    user_id=current_user.id,
                    raw_message=(payload.transcript or "").strip(),
                    reason="VOICE_LOW_CONFIDENCE_OR_UNRECOGNIZED",
                    assistant_reply=msg_fr,
                )
            )
            await db.commit()
        status_label = (
            "REPEAT_REQUIRED"
            if err_code in {"NOISE", "NOISE_DETECTED", "UNRECOGNIZED_SPEECH", "LOW_CONFIDENCE"}
            else "ERROR"
        )
        return VoiceCommandResponse(
            ok=False,
            status=status_label,
            trip_id=trip.id,
            provider_id=stt_provider.provider_id,
            provider_used=stt_provider.provider_id,
            provider_label_fr=stt_provider.provider_label_fr,
            language=stt_provider.language,
            transits_browser_service=stt_provider.transits_browser_service,
            privacy_notice_fr=stt_provider.privacy_notice_fr,
            hands_free=bool(payload.hands_free),
            execute_without_confirmation=bool(payload.execute_without_confirmation),
            editable_before_send=not bool(payload.hands_free),
            auto_submitted=bool(payload.hands_free),
            signal=str(stt_res.get("signal") or payload.signal),
            error_code=err_code,
            error_message_fr=msg_fr,
            recognized_transcript=str(stt_res.get("transcript") or ""),
            action_type="NONE",
            voice_command=None,
            navigation_target=None,
            day_number=None,
            spoken_reply_fr=msg_fr,
            requires_voice_confirmation=False,
            requires_confirmation=False,
            requires_double_confirmation=False,
            confirmation_steps_required=0,
            confirmation_step=0,
            pending_message_id=None,
            message_id=None,
            proposed_action=None,
            applied_change=False,
            message=None,
        )

    transcript_clean = str(stt_res.get("transcript") or "").strip()
    transcript_lower = transcript_clean.lower()

    # Commandes vocales de contrôle d'écoute ("Arrête d'écouter", "Écoute")
    if re.match(
        r"^\s*(?:arr[êe]te\s+d['’ ]?[ée]couter|arr[êe]ter\s+d['’ ]?[ée]couter|stop\s+[ée]coute|pause\s+[ée]coute)\s*[.!]*\s*$",
        transcript_lower,
    ):
        spoken_stop = "Écoute vocale mise en pause. Dites « Écoute » ou cliquez sur le bouton micro pour reprendre."
        return VoiceCommandResponse(
            ok=True,
            status="LISTENING_STOPPED",
            trip_id=trip.id,
            provider_id=stt_provider.provider_id,
            provider_used=stt_provider.provider_id,
            provider_label_fr=stt_provider.provider_label_fr,
            language=stt_provider.language,
            transits_browser_service=stt_provider.transits_browser_service,
            privacy_notice_fr=stt_provider.privacy_notice_fr,
            hands_free=bool(payload.hands_free),
            execute_without_confirmation=bool(payload.execute_without_confirmation),
            editable_before_send=not bool(payload.hands_free),
            auto_submitted=bool(payload.hands_free),
            signal="SPEECH",
            error_code=None,
            error_message_fr=None,
            recognized_transcript=transcript_clean,
            action_type="STOP_LISTENING",
            voice_command="STOP_LISTENING",
            navigation_target=None,
            day_number=None,
            spoken_reply_fr=spoken_stop,
            requires_voice_confirmation=False,
            requires_confirmation=False,
            requires_double_confirmation=False,
            confirmation_steps_required=0,
            confirmation_step=0,
            pending_message_id=None,
            message_id=None,
            proposed_action=None,
            applied_change=False,
            message=None,
        )

    if re.match(
        r"^\s*(?:[ée]coute|reprends?\s+l['’ ]?[ée]coute|active\s+l['’ ]?[ée]coute)\s*[.!]*\s*$",
        transcript_lower,
    ):
        spoken_resume = "Assistant vocal actif, dites une commande."
        return VoiceCommandResponse(
            ok=True,
            status="LISTENING_RESUMED",
            trip_id=trip.id,
            provider_id=stt_provider.provider_id,
            provider_used=stt_provider.provider_id,
            provider_label_fr=stt_provider.provider_label_fr,
            language=stt_provider.language,
            transits_browser_service=stt_provider.transits_browser_service,
            privacy_notice_fr=stt_provider.privacy_notice_fr,
            hands_free=bool(payload.hands_free),
            execute_without_confirmation=bool(payload.execute_without_confirmation),
            editable_before_send=not bool(payload.hands_free),
            auto_submitted=bool(payload.hands_free),
            signal="SPEECH",
            error_code=None,
            error_message_fr=None,
            recognized_transcript=transcript_clean,
            action_type="RESUME_LISTENING",
            voice_command="RESUME_LISTENING",
            navigation_target=None,
            day_number=None,
            spoken_reply_fr=spoken_resume,
            requires_voice_confirmation=False,
            requires_confirmation=False,
            requires_double_confirmation=False,
            confirmation_steps_required=0,
            confirmation_step=0,
            pending_message_id=None,
            message_id=None,
            proposed_action=None,
            applied_change=False,
            message=None,
        )

    # Commande vocale "Annule" / "Annuler" (sans nom de lieu derrière) -> restaure la dernière modification directe (< 30 s)
    if re.match(
        r"^\s*(?:annule|annuler|annulez|annule\s+la\s+modification|annuler\s+la\s+modification|annule\s+le\s+changement)\s*[.!]*\s*$",
        transcript_lower,
    ):
        await require_trip_access(
            db,
            trip_id,
            current_user.id,
            allowed_roles=WRITE_ROLES,
        )
        undo_res = await _execute_voice_undo_for_trip(
            db=db,
            trip=trip,
            destination=destination,
            message_id=None,
            source="VOICE",
        )
        return VoiceCommandResponse(
            ok=undo_res.ok,
            status=undo_res.status,
            trip_id=trip.id,
            provider_id=stt_provider.provider_id,
            provider_used=stt_provider.provider_id,
            provider_label_fr=stt_provider.provider_label_fr,
            language=stt_provider.language,
            transits_browser_service=stt_provider.transits_browser_service,
            privacy_notice_fr=stt_provider.privacy_notice_fr,
            hands_free=bool(payload.hands_free),
            execute_without_confirmation=bool(payload.execute_without_confirmation),
            editable_before_send=not bool(payload.hands_free),
            auto_submitted=bool(payload.hands_free),
            signal="SPEECH",
            error_code=None if undo_res.ok else undo_res.status,
            error_message_fr=None if undo_res.ok else undo_res.detail_fr,
            recognized_transcript=transcript_clean,
            action_type="UNDO",
            voice_command="UNDO_LAST_MODIFICATION",
            navigation_target=None,
            day_number=None,
            spoken_reply_fr=undo_res.spoken_reply_fr,
            requires_voice_confirmation=False,
            requires_confirmation=False,
            requires_double_confirmation=False,
            confirmation_steps_required=0,
            confirmation_step=0,
            pending_message_id=None,
            message_id=undo_res.message_id,
            proposed_action=None,
            applied_change=undo_res.restored,
            executed_directly=False,
            can_undo=False,
            undo_window_seconds=0,
            restored_item=undo_res.restored_item,
            deleted_item_id=undo_res.deleted_item_id,
            last_modification_history=undo_res.last_modification_history,
            message=undo_res.message,
        )

    # Analyse de l'intention avec le même analyseur que le chat
    safe_context, _places_by_id, _existing_items = await _build_safe_trip_context_for_chat(
        db,
        trip,
        destination,
        current_user_id=current_user.id,
        user_role=user_role,
    )
    prev_msgs_res = await db.scalars(
        select(ChatMessage)
        .where(ChatMessage.trip_id == trip.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(10)
    )
    prev_msgs = list(reversed(prev_msgs_res.all()))
    history_for_ai = [
        {
            "role": m.sender_role,
            "content": m.content,
            "proposed_action": m.proposed_action,
            "action_status": m.action_status,
        }
        for m in prev_msgs
    ]

    rules_provider = SimulatedAIProvider(get_settings())
    raw_rules = await rules_provider.generate_chat_reply(
        user_message=transcript_clean,
        safe_trip_context=safe_context,
        chat_history=history_for_ai,
    )
    validated_voice = _validate_and_normalize_chat_llm_payload(raw_rules)
    act_type = str(validated_voice.get("action_type") or "NONE")

    # 1. Commandes de navigation ou de lecture vocale (READ_ROLES suffisant)
    if act_type in {"NAVIGATE", "READ_DAY", "READ_BUDGET", "OPEN_DOCUMENTS", "OPEN_PRACTICAL_INFO", "INFO"}:
        reply_fr = str(validated_voice.get("reply") or "").strip()
        nav_target = validated_voice.get("navigation_target")
        v_cmd = validated_voice.get("voice_command") or act_type
        day_num = validated_voice.get("day_number")

        user_msg = ChatMessage(
            trip_id=trip.id,
            sender_role="user",
            content=transcript_clean,
            proposed_action=None,
            action_status="NONE",
        )
        assistant_msg = ChatMessage(
            trip_id=trip.id,
            sender_role="assistant",
            content=reply_fr,
            proposed_action=None,
            action_status="NONE",
        )
        db.add(user_msg)
        db.add(assistant_msg)
        await db.commit()
        await db.refresh(assistant_msg)

        msg_schema = _serialize_chat_message(assistant_msg)
        msg_schema.navigation_target = nav_target
        msg_schema.voice_command = v_cmd

        is_hf = bool(payload.hands_free)
        return VoiceCommandResponse(
            ok=True,
            status="OK" if is_hf else "TRANSCRIBED_EDITABLE",
            trip_id=trip.id,
            provider_id=stt_provider.provider_id,
            provider_used=stt_provider.provider_id,
            provider_label_fr=stt_provider.provider_label_fr,
            language=stt_provider.language,
            transits_browser_service=stt_provider.transits_browser_service,
            privacy_notice_fr=stt_provider.privacy_notice_fr,
            hands_free=is_hf,
            execute_without_confirmation=bool(payload.execute_without_confirmation),
            editable_before_send=not is_hf,
            auto_submitted=is_hf,
            signal="SPEECH",
            error_code=None,
            error_message_fr=None,
            recognized_transcript=transcript_clean,
            action_type=act_type,
            voice_command=v_cmd,
            navigation_target=nav_target,
            day_number=int(day_num) if day_num is not None else None,
            spoken_reply_fr=reply_fr,
            requires_voice_confirmation=False,
            requires_confirmation=False,
            requires_double_confirmation=False,
            confirmation_steps_required=0,
            confirmation_step=0,
            pending_message_id=None,
            message_id=assistant_msg.id,
            proposed_action=None,
            applied_change=False,
            message=msg_schema,
        )

    # 2. Lieu ambigu, lieu inconnu avec intention d'action, ou parole non comprise
    raw_prop = validated_voice.get("proposed_action")
    ask_reason = str(validated_voice.get("ask_reason") or "")
    has_action_verb_in_transcript = bool(
        re.search(
            r"\b(ajoute|ajouter|rajoute|rajouter|mets|mettre|planifie|planifier|programme|programmer|"
            r"d[ée]place|d[ée]placer|change|changer|modifie|modifier|d[ée]cale|d[ée]caler|repousse|repousser|"
            r"avance|avancer|supprime|supprimer|retire|retirer|enl[èe]ve|enlever|visite|visiter|aller)\b",
            transcript_lower,
        )
    )
    if act_type in {"ASK", "NONE"} and not isinstance(raw_prop, dict):
        base_reply = str(validated_voice.get("reply") or "").strip()
        # Si c'est une question de clarification (lieu ambigu, lieu inconnu sur commande d'action, ou date/heure manquante) :
        # question posée à voix haute et enregistrée dans le chat, aucune exécution.
        if (
            ask_reason == "AMBIGUOUS_PLACE"
            or (ask_reason == "UNKNOWN_PLACE" and has_action_verb_in_transcript)
            or bool(validated_voice.get("place_name"))
        ):
            user_msg = ChatMessage(
                trip_id=trip.id,
                sender_role="user",
                content=transcript_clean,
                proposed_action=None,
                action_status="NONE",
            )
            assistant_msg = ChatMessage(
                trip_id=trip.id,
                sender_role="assistant",
                content=base_reply,
                proposed_action=None,
                action_status="NONE",
            )
            db.add(user_msg)
            db.add(assistant_msg)
            await db.commit()
            await db.refresh(assistant_msg)
            return VoiceCommandResponse(
                ok=True,
                status="ASK",
                trip_id=trip.id,
                provider_id=stt_provider.provider_id,
                provider_used=stt_provider.provider_id,
                provider_label_fr=stt_provider.provider_label_fr,
                language=stt_provider.language,
                transits_browser_service=stt_provider.transits_browser_service,
                privacy_notice_fr=stt_provider.privacy_notice_fr,
                hands_free=bool(payload.hands_free),
                execute_without_confirmation=bool(payload.execute_without_confirmation),
                editable_before_send=not bool(payload.hands_free),
                auto_submitted=bool(payload.hands_free),
                signal="SPEECH",
                error_code=ask_reason or None,
                error_message_fr=None,
                recognized_transcript=transcript_clean,
                action_type="ASK",
                voice_command=None,
                navigation_target=None,
                day_number=None,
                spoken_reply_fr=base_reply,
                requires_voice_confirmation=False,
                requires_confirmation=False,
                requires_double_confirmation=False,
                confirmation_steps_required=0,
                confirmation_step=0,
                pending_message_id=None,
                message_id=assistant_msg.id,
                proposed_action=None,
                applied_change=False,
                executed_directly=False,
                message=_serialize_chat_message(assistant_msg),
            )

        if "pouvez-vous répéter" not in base_reply.lower():
            spoken_repeat = f"Pouvez-vous répéter ? {base_reply}".strip()
        else:
            spoken_repeat = base_reply
        db.add(
            ChatUnrecognized(
                trip_id=trip.id,
                user_id=current_user.id,
                raw_message=transcript_clean,
                reason="VOICE_UNRECOGNIZED_COMMAND",
                assistant_reply=spoken_repeat,
            )
        )
        await db.commit()
        return VoiceCommandResponse(
            ok=False,
            status="REPEAT_REQUIRED",
            trip_id=trip.id,
            provider_id=stt_provider.provider_id,
            provider_used=stt_provider.provider_id,
            provider_label_fr=stt_provider.provider_label_fr,
            language=stt_provider.language,
            transits_browser_service=stt_provider.transits_browser_service,
            privacy_notice_fr=stt_provider.privacy_notice_fr,
            hands_free=bool(payload.hands_free),
            execute_without_confirmation=bool(payload.execute_without_confirmation),
            editable_before_send=not bool(payload.hands_free),
            auto_submitted=bool(payload.hands_free),
            signal="UNRECOGNIZED_SPEECH",
            error_code="UNRECOGNIZED_SPEECH",
            error_message_fr=spoken_repeat,
            recognized_transcript=transcript_clean,
            action_type=act_type,
            voice_command=None,
            navigation_target=None,
            day_number=None,
            spoken_reply_fr=spoken_repeat,
            requires_voice_confirmation=False,
            requires_confirmation=False,
            requires_double_confirmation=False,
            confirmation_steps_required=0,
            confirmation_step=0,
            pending_message_id=None,
            message_id=None,
            proposed_action=None,
            applied_change=False,
            message=None,
        )

    # 3. Commande d'action (ADD_VISIT, MOVE_VISIT, REMOVE_VISIT, BOOK_RESERVATION, PROCESS_PAYMENT) :
    #    - Contrôle d'accès en écriture strict (OWNER / EDITOR uniquement -> 403 pour VIEWER)
    await require_trip_access(
        db,
        trip_id,
        current_user.id,
        allowed_roles=WRITE_ROLES,
    )

    # Capture de l'état avant modification pour l'historique d'annulation (si exécution directe)
    pre_items_map: dict[str, dict[str, Any]] = {}
    if payload.execute_without_confirmation:
        dest_tz = destination.timezone or "UTC"
        existing_before, _ = await _load_trip_items_with_places(db, trip.id)
        for it_b in existing_before:
            loc_b = to_destination_local(ensure_utc(it_b.start_at), dest_tz)
            pre_items_map[it_b.id] = {
                "item_id": it_b.id,
                "place_id": it_b.place_id,
                "previous_visit_date": it_b.visit_date.isoformat(),
                "previous_local_start_time": loc_b.strftime("%H:%M"),
                "previous_start_at_utc": ensure_utc(it_b.start_at).isoformat(),
                "previous_end_at_utc": ensure_utc(it_b.end_at).isoformat(),
                "previous_duration_minutes": it_b.duration_minutes,
                "previous_transit_mode": it_b.transit_mode_to_next,
                "previous_calendar_sync_status": it_b.calendar_sync_status,
                "previous_google_calendar_event_id": it_b.google_calendar_event_id,
            }

    conv_resp = await send_trip_chat_message(
        trip_id=trip.id,
        payload=ChatSendMessageRequest(message=transcript_clean),
        current_user=current_user,
        db=db,
    )
    last_msg = conv_resp.messages[-1] if conv_resp.messages else None
    prop = last_msg.proposed_action if last_msg else None

    if prop is None or not last_msg or last_msg.action_status != "PENDING_CONFIRMATION":
        reply_txt = last_msg.content if last_msg else "Pouvez-vous répéter votre demande ?"
        return VoiceCommandResponse(
            ok=True,
            status="ASK",
            trip_id=trip.id,
            provider_id=stt_provider.provider_id,
            provider_used=stt_provider.provider_id,
            provider_label_fr=stt_provider.provider_label_fr,
            language=stt_provider.language,
            transits_browser_service=stt_provider.transits_browser_service,
            privacy_notice_fr=stt_provider.privacy_notice_fr,
            hands_free=bool(payload.hands_free),
            execute_without_confirmation=bool(payload.execute_without_confirmation),
            editable_before_send=not bool(payload.hands_free),
            auto_submitted=bool(payload.hands_free),
            signal="SPEECH",
            error_code=None,
            error_message_fr=None,
            recognized_transcript=transcript_clean,
            action_type="ASK",
            voice_command=None,
            navigation_target=None,
            day_number=None,
            spoken_reply_fr=reply_txt,
            requires_voice_confirmation=False,
            requires_confirmation=False,
            requires_double_confirmation=False,
            confirmation_steps_required=0,
            confirmation_step=0,
            pending_message_id=None,
            message_id=last_msg.id if last_msg else None,
            proposed_action=None,
            applied_change=False,
            message=last_msg,
        )

    # Si le créneau demandé est impossible (fermé, hors voyage, chevauchement) et que l'exécution sans confirmation est activée :
    # question à voix haute, aucune exécution directe (Exigence 4).
    if payload.execute_without_confirmation and not prop.validated_by_engine:
        base_invalid = last_msg.content.strip()
        if "?" not in base_invalid:
            spoken_invalid_q = f"{base_invalid} Souhaitez-vous retenir ce créneau proposé ou choisir une autre heure ?"
        else:
            spoken_invalid_q = base_invalid
        return VoiceCommandResponse(
            ok=True,
            status="ASK",
            trip_id=trip.id,
            provider_id=stt_provider.provider_id,
            provider_used=stt_provider.provider_id,
            provider_label_fr=stt_provider.provider_label_fr,
            language=stt_provider.language,
            transits_browser_service=stt_provider.transits_browser_service,
            privacy_notice_fr=stt_provider.privacy_notice_fr,
            hands_free=bool(payload.hands_free),
            execute_without_confirmation=True,
            editable_before_send=not bool(payload.hands_free),
            auto_submitted=bool(payload.hands_free),
            signal="SPEECH",
            error_code=prop.validation_error_code,
            error_message_fr=prop.validation_message_fr,
            recognized_transcript=transcript_clean,
            action_type="ASK",
            voice_command=prop.action_type,
            navigation_target=None,
            day_number=None,
            spoken_reply_fr=spoken_invalid_q,
            requires_voice_confirmation=False,
            requires_confirmation=False,
            requires_double_confirmation=False,
            confirmation_steps_required=0,
            confirmation_step=0,
            pending_message_id=last_msg.id,
            message_id=last_msg.id,
            proposed_action=prop,
            applied_change=False,
            executed_directly=False,
            place_similarity_score=prop.place_similarity_score,
            has_explicit_date=prop.explicit_date,
            has_explicit_time=prop.explicit_time,
            message=last_msg,
        )

    # Exigence 3 & 4 : Exécution directe sans confirmation UNIQUEMENT pour ADD_VISIT ou MOVE_VISIT si :
    # - Option execute_without_confirmation activée
    # - Lieu reconnu avec un score élevé (>= 0.75)
    # - Date et heure explicites (explicit_date et explicit_time)
    # - Créneau valide pour le moteur de validation (validated_by_engine == True)
    # - Confiance STT élevée (>= 0.75)
    # Jamais pour REMOVE_VISIT, BOOK_RESERVATION ou PROCESS_PAYMENT.
    sim_score = float(prop.place_similarity_score if prop.place_similarity_score is not None else 0.0)
    can_execute_directly = bool(
        payload.execute_without_confirmation
        and prop.action_type in {"ADD_VISIT", "MOVE_VISIT"}
        and prop.validated_by_engine
        and sim_score >= 0.75
        and prop.explicit_date
        and prop.explicit_time
        and float(payload.confidence) >= 0.75
    )

    if can_execute_directly:
        decision_res = await confirm_chat_proposed_action(
            trip_id=trip.id,
            message_id=last_msg.id,
            override_visit_date=None,
            override_local_start_time=None,
            current_user=current_user,
            db=db,
        )
        updated_it = decision_res.updated_item
        applied_item_id = updated_it.id if updated_it else prop.item_id
        prev_snap = pre_items_map.get(str(applied_item_id or prop.item_id or ""), {})
        v_date_obj = date.fromisoformat(prop.visit_date)
        if prop.action_type == "MOVE_VISIT":
            spoken_done = (
                f"C'est fait : « {prop.place_name} » a été déplacé au "
                f"{_format_date_fr(v_date_obj)} à {prop.local_start_time}. "
                "Vous avez 30 secondes pour dire « Annule » ou cliquer sur Annuler."
            )
        else:
            spoken_done = (
                f"C'est fait : « {prop.place_name} » a été ajouté le "
                f"{_format_date_fr(v_date_obj)} à {prop.local_start_time}. "
                "Vous avez 30 secondes pour dire « Annule » ou cliquer sur Annuler."
            )

        undo_snapshot: dict[str, Any] = {
            "action_type": prop.action_type,
            "item_id": applied_item_id,
            "place_id": prop.place_id,
            "place_name": prop.place_name,
            "new_visit_date": prop.visit_date,
            "new_local_start_time": prop.local_start_time,
            "previous_visit_date": prev_snap.get("previous_visit_date"),
            "previous_local_start_time": prev_snap.get("previous_local_start_time"),
            "previous_start_at_utc": prev_snap.get("previous_start_at_utc"),
            "previous_end_at_utc": prev_snap.get("previous_end_at_utc"),
            "previous_duration_minutes": prev_snap.get("previous_duration_minutes"),
            "previous_transit_mode": prev_snap.get("previous_transit_mode"),
            "previous_calendar_sync_status": prev_snap.get("previous_calendar_sync_status"),
            "calendar_sync_status": updated_it.calendar_sync_status if updated_it else "SYNCED",
            "executed_at_epoch": round(time.time(), 3),
            "executed_at_iso": datetime.now().isoformat(),
            "undo_window_seconds": 30,
            "undone": False,
        }

        msg_db = await db.scalar(
            select(ChatMessage).where(ChatMessage.id == last_msg.id, ChatMessage.trip_id == trip.id)
        )
        if msg_db is not None and isinstance(msg_db.proposed_action, dict):
            updated_prop_dict = dict(msg_db.proposed_action)
            updated_prop_dict["executed_directly"] = True
            updated_prop_dict["undo_available"] = True
            updated_prop_dict["undo_window_seconds"] = 30
            updated_prop_dict["undo_snapshot"] = undo_snapshot
            updated_prop_dict["spoken_summary_fr"] = spoken_done
            msg_db.proposed_action = updated_prop_dict
            msg_db.action_status = "EXECUTED_DIRECTLY"
            msg_db.content = spoken_done
            await db.commit()
            await db.refresh(msg_db)
            serialized_msg = _serialize_chat_message(msg_db)
            prop_out = serialized_msg.proposed_action
        else:
            serialized_msg = decision_res.message
            prop_out = prop

        return VoiceCommandResponse(
            ok=True,
            status="EXECUTED_DIRECTLY",
            trip_id=trip.id,
            provider_id=stt_provider.provider_id,
            provider_used=stt_provider.provider_id,
            provider_label_fr=stt_provider.provider_label_fr,
            language=stt_provider.language,
            transits_browser_service=stt_provider.transits_browser_service,
            privacy_notice_fr=stt_provider.privacy_notice_fr,
            hands_free=bool(payload.hands_free),
            execute_without_confirmation=True,
            editable_before_send=not bool(payload.hands_free),
            auto_submitted=bool(payload.hands_free),
            signal="SPEECH",
            error_code=None,
            error_message_fr=None,
            recognized_transcript=transcript_clean,
            action_type=prop.action_type,
            voice_command=prop.action_type,
            navigation_target=None,
            day_number=None,
            spoken_reply_fr=spoken_done,
            requires_voice_confirmation=False,
            requires_confirmation=False,
            requires_double_confirmation=False,
            confirmation_steps_required=0,
            confirmation_step=0,
            pending_message_id=None,
            message_id=last_msg.id,
            proposed_action=prop_out,
            applied_change=True,
            executed_directly=True,
            can_undo=True,
            undo_window_seconds=30,
            undo_message_id=last_msg.id,
            place_similarity_score=sim_score,
            has_explicit_date=prop.explicit_date,
            has_explicit_time=prop.explicit_time,
            updated_item=updated_it,
            last_modification_history=undo_snapshot,
            message=serialized_msg,
        )

    needs_double = bool(
        prop.requires_double_confirmation
        or prop.action_type in {"REMOVE_VISIT", "BOOK_RESERVATION", "PROCESS_PAYMENT"}
    )
    steps_req = 2 if needs_double else 1
    base_content = last_msg.content.strip()
    if needs_double:
        if "double confirmation" not in base_content.lower():
            spoken_prompt = (
                f"Action comprise : {base_content} "
                "Cette action sensible nécessite une double confirmation vocale : "
                "dites explicitement « oui » une première fois pour continuer, ou « non » (ou gardez le silence) pour annuler."
            )
        else:
            spoken_prompt = base_content
    else:
        if "dites « oui »" not in base_content.lower() and "dites oui" not in base_content.lower():
            spoken_prompt = (
                f"Action comprise : {base_content} "
                "Dites explicitement « oui » pour confirmer, ou « non » (ou gardez le silence) pour annuler."
            )
        else:
            spoken_prompt = base_content

    if not prop.spoken_summary_fr:
        prop.spoken_summary_fr = spoken_prompt

    return VoiceCommandResponse(
        ok=True,
        status="PENDING_CONFIRMATION",
        trip_id=trip.id,
        provider_id=stt_provider.provider_id,
        provider_used=stt_provider.provider_id,
        provider_label_fr=stt_provider.provider_label_fr,
        language=stt_provider.language,
        transits_browser_service=stt_provider.transits_browser_service,
        privacy_notice_fr=stt_provider.privacy_notice_fr,
        hands_free=bool(payload.hands_free),
        execute_without_confirmation=bool(payload.execute_without_confirmation),
        editable_before_send=not bool(payload.hands_free),
        auto_submitted=bool(payload.hands_free),
        signal="SPEECH",
        error_code=None,
        error_message_fr=None,
        recognized_transcript=transcript_clean,
        action_type=prop.action_type,
        voice_command=prop.action_type,
        navigation_target=None,
        day_number=None,
        spoken_reply_fr=spoken_prompt,
        requires_voice_confirmation=True,
        requires_confirmation=True,
        requires_double_confirmation=needs_double,
        confirmation_steps_required=steps_req,
        confirmation_step=1,
        pending_message_id=last_msg.id,
        message_id=last_msg.id,
        proposed_action=prop,
        applied_change=False,
        executed_directly=False,
        place_similarity_score=sim_score,
        has_explicit_date=prop.explicit_date,
        has_explicit_time=prop.explicit_time,
        message=last_msg,
    )


async def _handle_voice_confirmation_decision(
    *,
    trip_id: str,
    message_id: str | None,
    payload: VoiceConfirmRequest,
    current_user: User,
    db: AsyncSession,
) -> VoiceConfirmResponse:
    trip, _destination = await _load_trip_and_destination_strict(
        db,
        trip_id,
        current_user.id,
        write=True,
    )

    if message_id:
        msg = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.id == message_id,
                ChatMessage.trip_id == trip.id,
            )
        )
    else:
        res = await db.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.trip_id == trip.id,
                ChatMessage.action_status.in_(["PENDING_CONFIRMATION", "AWAITING_SECOND_CONFIRMATION"]),
            )
            .order_by(ChatMessage.created_at.desc())
        )
        msg = res.first()

    if not msg or not msg.proposed_action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune proposition d'action en attente de confirmation vocale.",
        )
    if msg.action_status == "CONFIRMED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette proposition a déjà été confirmée.",
        )

    action = dict(msg.proposed_action)
    act_type = str(action.get("action_type") or "")
    needs_double = bool(
        action.get("requires_double_confirmation")
        or act_type in {"REMOVE_VISIT", "BOOK_RESERVATION", "PROCESS_PAYMENT"}
    )
    steps_req = 2 if needs_double else 1
    cur_step = int(action.get("confirmation_step") or 1)

    sig = (payload.signal or "SPEECH").strip().upper()
    raw_txt = (payload.transcript or "").strip()
    txt_norm = "".join(
        c for c in unicodedata.normalize("NFD", raw_txt.lower()) if unicodedata.category(c) != "Mn"
    )

    # 1. Erreurs micro / navigateur / bruit / erreur de reconnaissance -> AUCUNE modification, proposition préservée
    if sig in {"MIC_DENIED", "BROWSER_UNSUPPORTED", "NOISE", "UNRECOGNIZED_SPEECH"} or (
        sig != "SILENCE" and payload.confidence < 0.35
    ):
        err_code = sig if sig != "SPEECH" else "UNRECOGNIZED_SPEECH"
        spoken = (
            "Pouvez-vous répéter ? Dites explicitement « oui » pour confirmer ou « non » pour annuler. "
            "Aucune modification n'a été effectuée."
        )
        if err_code == "MIC_DENIED":
            spoken = (
                "Accès au microphone refusé. Aucune modification n'a été appliquée à votre programme."
            )
        elif err_code == "BROWSER_UNSUPPORTED":
            spoken = (
                "Navigateur non compatible avec la reconnaissance vocale. Aucune modification n'a été appliquée."
            )
        elif err_code == "NOISE":
            spoken = (
                "Bruit ambiant détecté. Pouvez-vous répéter « oui » ou « non » ? Aucune modification n'a été appliquée."
            )
        return VoiceConfirmResponse(
            ok=False,
            status="ERROR_NO_MODIFICATION",
            trip_id=trip.id,
            message_id=msg.id,
            decision="ERROR_NO_MODIFICATION",
            action_status=msg.action_status,  # type: ignore[arg-type]
            applied_change=False,
            pending_action_preserved=True,
            requires_double_confirmation=needs_double,
            confirmation_steps_required=steps_req,
            confirmation_step=cur_step,
            error_code=err_code,
            spoken_reply_fr=spoken,
            detail_fr=spoken,
            message=_serialize_chat_message(msg),
        )

    # 2. Silence -> annule immédiatement la proposition sans modifier le programme
    if sig == "SILENCE" or not txt_norm or re.search(r"^\s*(silence|muet)\s*$", txt_norm):
        msg.action_status = "REJECTED"
        await db.commit()
        await db.refresh(msg)
        spoken = "Silence détecté : l'action est annulée et aucune modification n'a été appliquée."
        return VoiceConfirmResponse(
            ok=True,
            status="CANCELLED_BY_SILENCE",
            trip_id=trip.id,
            message_id=msg.id,
            decision="CANCELLED_BY_SILENCE",
            action_status="REJECTED",
            applied_change=False,
            pending_action_preserved=False,
            requires_double_confirmation=needs_double,
            confirmation_steps_required=steps_req,
            confirmation_step=cur_step,
            error_code=None,
            spoken_reply_fr=spoken,
            detail_fr=spoken,
            message=_serialize_chat_message(msg),
        )

    # 3. "Non" explicite -> annule immédiatement la proposition sans modifier le programme
    has_no = bool(re.search(r"\b(non|annule|annuler|annulation|refuse|refuser|stop|jamais)\b", txt_norm))
    has_yes = bool(re.search(r"\b(oui)\b", txt_norm)) and not has_no

    if has_no:
        msg.action_status = "REJECTED"
        await db.commit()
        await db.refresh(msg)
        spoken = "Confirmation refusée (« non ») : l'action est annulée et votre programme reste inchangé."
        return VoiceConfirmResponse(
            ok=True,
            status="REJECTED",
            trip_id=trip.id,
            message_id=msg.id,
            decision="CANCELLED_BY_NO",
            action_status="REJECTED",
            applied_change=False,
            pending_action_preserved=False,
            requires_double_confirmation=needs_double,
            confirmation_steps_required=steps_req,
            confirmation_step=cur_step,
            error_code=None,
            spoken_reply_fr=spoken,
            detail_fr=spoken,
            message=_serialize_chat_message(msg),
        )

    # 4. Parole qui n'est ni "oui" explicite ni "non" -> demande de répéter sans rien modifier
    if not has_yes:
        spoken = (
            "Pouvez-vous répéter ? Pour votre sécurité, je n'applique jamais de validation automatique : "
            "dites explicitement « oui » pour confirmer ou « non » pour annuler."
        )
        return VoiceConfirmResponse(
            ok=False,
            status="REPEAT_REQUIRED",
            trip_id=trip.id,
            message_id=msg.id,
            decision="REPEAT_REQUIRED",
            action_status=msg.action_status,  # type: ignore[arg-type]
            applied_change=False,
            pending_action_preserved=True,
            requires_double_confirmation=needs_double,
            confirmation_steps_required=steps_req,
            confirmation_step=cur_step,
            error_code="UNRECOGNIZED_SPEECH",
            spoken_reply_fr=spoken,
            detail_fr=spoken,
            message=_serialize_chat_message(msg),
        )

    # 5. "Oui" explicite reçu :
    #    - Si double confirmation requise (réservation, paiement, suppression) et étape 1 -> passe à l'étape 2 sans appliquer
    if needs_double and cur_step < 2:
        action["requires_double_confirmation"] = True
        action["confirmation_steps_required"] = 2
        action["confirmation_step"] = 2
        msg.proposed_action = action
        msg.action_status = "AWAITING_SECOND_CONFIRMATION"
        await db.commit()
        await db.refresh(msg)
        place_lbl = str(action.get("place_name") or "cette action")
        spoken = (
            f"Première confirmation « oui » enregistrée pour « {place_lbl} ». "
            "Attention : s'agissant d'une suppression, d'une réservation ou d'un paiement, "
            "une seconde confirmation vocale est requise. Dites une deuxième fois « oui » pour valider définitivement, "
            "ou « non » pour annuler."
        )
        return VoiceConfirmResponse(
            ok=True,
            status="AWAITING_SECOND_CONFIRMATION",
            trip_id=trip.id,
            message_id=msg.id,
            decision="AWAITING_SECOND_CONFIRMATION",
            action_status="AWAITING_SECOND_CONFIRMATION",
            applied_change=False,
            pending_action_preserved=True,
            requires_double_confirmation=True,
            confirmation_steps_required=2,
            confirmation_step=2,
            error_code=None,
            spoken_reply_fr=spoken,
            detail_fr=spoken,
            message=_serialize_chat_message(msg),
        )

    # 6. Validation finale ("oui" sur action simple, ou 2e "oui" sur action à double confirmation)
    decision_res = await confirm_chat_proposed_action(
        trip_id=trip.id,
        message_id=msg.id,
        override_visit_date=None,
        override_local_start_time=None,
        current_user=current_user,
        db=db,
    )
    return VoiceConfirmResponse(
        ok=True,
        status="CONFIRMED",
        trip_id=trip.id,
        message_id=msg.id,
        decision="CONFIRMED",
        action_status="CONFIRMED",
        applied_change=decision_res.applied_change,
        pending_action_preserved=False,
        requires_double_confirmation=needs_double,
        confirmation_steps_required=steps_req,
        confirmation_step=steps_req,
        error_code=None,
        spoken_reply_fr=decision_res.detail_fr,
        detail_fr=decision_res.detail_fr,
        updated_item=decision_res.updated_item,
        deleted_item_id=decision_res.deleted_item_id,
        message=decision_res.message,
    )


@router.post("/trip/{trip_id}/voice/confirm", response_model=VoiceConfirmResponse)
async def confirm_trip_voice_action(
    trip_id: str,
    payload: VoiceConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VoiceConfirmResponse:
    """
    Confirme ou annule vocalement la dernière proposition en attente sur le voyage.
    """
    return await _handle_voice_confirmation_decision(
        trip_id=trip_id,
        message_id=payload.message_id,
        payload=payload,
        current_user=current_user,
        db=db,
    )


@router.post("/trip/{trip_id}/chat/{message_id}/voice-confirm", response_model=VoiceConfirmResponse)
async def confirm_specific_chat_message_by_voice(
    trip_id: str,
    message_id: str,
    payload: VoiceConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VoiceConfirmResponse:
    """
    Confirme ou annule vocalement une proposition spécifique identifiée par message_id.
    """
    return await _handle_voice_confirmation_decision(
        trip_id=trip_id,
        message_id=message_id,
        payload=payload,
        current_user=current_user,
        db=db,
    )

