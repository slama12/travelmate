from datetime import date, datetime, timedelta
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import select

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
from app.core.providers import get_provider_registry
from app.core.redis import cache_client
from app.models.entities import (
    Accommodation,
    ChatMessage,
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
    return [base + timedelta(days=i) for i in range(5)]


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
                        f"le {c_loc_s.strftime('%Y-%m-%d')} de {c_loc_s.strftime('%H:%M')} à {c_loc_e.strftime('%H:%M')}"
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
                        f"Déplacer « {place.name} » au {a_loc_s.strftime('%Y-%m-%d')} "
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
                    f"Météo défavorable prévue le {visit_date_str} ({day_weather.summary}) "
                    f"pendant votre visite en extérieur « {place.name} ». "
                    "Souhaitez-vous la remplacer par un lieu en intérieur ou la décaler ?"
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
    - Filtre strictement les lieux existants en base pour la destination,
    - Passe chaque créneau dans le moteur de validation (correction ou retrait avec message clair),
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

    max_attempts = 2
    parsed_plan: AIModelRawPlanSchema | None = None
    last_validation_error: str | None = None
    attempts_used = 0

    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
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

    trip_arr_utc = ensure_utc(trip.arrival_at) if trip.arrival_at else None
    trip_dep_utc = ensure_utc(trip.departure_at) if trip.departure_at else None

    for idx, raw_slot in enumerate(parsed_plan.slots):
        place = places_by_id.get(raw_slot.place_id)
        if place is None:
            adjustments_fr.append(
                f"Lieu inexistant en base (« {raw_slot.place_name or raw_slot.place_id} ») ignoré et retiré."
            )
            continue

        dur_min = int(raw_slot.duration_minutes or place.recommended_duration_min or 90)
        transit_mode = normalize_transit_mode(raw_slot.transit_mode)
        req_start_utc, req_end_utc = parse_local_slot_to_utc(
            visit_date=raw_slot.visit_date,
            local_start_time_str=raw_slot.local_start_time,
            duration_minutes=dur_min,
            timezone_name=dest_tz,
        )

        weather_adapted = False
        adjustment_note: str | None = None

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
        validation_status: str = "VALID"

        if not val_res.valid:
            corrected = False
            for sug in val_res.suggested_slots:
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
                    adjustment_note = (
                        f"Créneau initial ({raw_slot.visit_date.isoformat()} {raw_slot.local_start_time}) "
                        f"refusé pour « {place.name} » ({val_res.message}) → "
                        f"corrigé vers {sug.local_date} à {sug.local_start_time}."
                    )
                    adjustments_fr.append(adjustment_note)
                    corrected = True
                    break

            if not corrected:
                adjustments_fr.append(
                    f"Créneau ({raw_slot.visit_date.isoformat()} {raw_slot.local_start_time}) "
                    f"refusé et retiré pour « {place.name} » : {val_res.message}"
                )
                continue

        loc_s = to_destination_local(chosen_start_utc, dest_tz)
        loc_e = to_destination_local(chosen_end_utc, dest_tz)
        final_date_str = loc_s.strftime("%Y-%m-%d")
        final_day_w = weather_by_date.get(final_date_str, {})
        if final_day_w.get("available", True) and final_day_w.get("is_rainy") and not place.is_outdoor:
            weather_adapted = True

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

        draft_items.append(
            AIDraftSlotSchema(
                place_id=p.id,
                place_name=p.name,
                place_category=p.category,
                is_outdoor=bool(p.is_outdoor),
                visit_date=entry["loc_s"].date(),
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


@router.post("/trip/{trip_id}/chat", response_model=ChatConversationResponse)
async def send_trip_chat_message(
    trip_id: str,
    payload: ChatSendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatConversationResponse:
    """
    Envoie un message à l'assistant du voyage :
    - Contrôle d'accès strict (403 si le voyage appartient à un autre utilisateur),
    - Historique limité à ce seul voyage,
    - Aucune exposition des documents du coffre-fort ni des jetons Google,
    - Si l'assistant propose d'ajouter, déplacer ou retirer une visite, l'action passe par le
      moteur de validation et reste en statut 'PENDING_CONFIRMATION' (rien n'est modifié sans accord).
    """
    registry = get_provider_registry()
    trip, destination = await _load_trip_and_destination_strict(db, trip_id, current_user.id)
    dest_tz = destination.timezone or "UTC"

    hist_res = await db.scalars(
        select(ChatMessage)
        .where(ChatMessage.trip_id == trip.id)
        .order_by(ChatMessage.created_at.asc())
    )
    history_rows = list(hist_res.all())
    history_for_ai = [{"role": m.sender_role, "content": m.content} for m in history_rows[-10:]]

    safe_context, places_by_id, existing_items = await _build_safe_trip_context_for_chat(
        db, trip, destination
    )

    user_msg = ChatMessage(
        trip_id=trip.id,
        sender_role="user",
        content=payload.message.strip(),
        proposed_action=None,
        action_status="NONE",
    )
    db.add(user_msg)

    ai_result = await registry.ai.generate_chat_reply(
        user_message=payload.message.strip(),
        safe_trip_context=safe_context,
        chat_history=history_for_ai,
    )
    reply_text = str(ai_result.get("reply") or "Je suis à votre disposition pour votre voyage.")
    raw_action = ai_result.get("proposed_action")

    proposed_action_dict: dict[str, Any] | None = None
    action_status = "NONE"

    if isinstance(raw_action, dict) and raw_action.get("action_type") in {
        "ADD_VISIT",
        "MOVE_VISIT",
        "REMOVE_VISIT",
    }:
        act_type = str(raw_action["action_type"])
        place_id = str(raw_action.get("place_id") or "")
        place_obj = places_by_id.get(place_id)
        v_date_str = str(
            raw_action.get("visit_date") or _compute_trip_dates_local(trip, dest_tz)[0].isoformat()
        )
        v_time_str = str(raw_action.get("local_start_time") or "14:00")
        dur_min = int(
            raw_action.get("duration_minutes") or (place_obj.recommended_duration_min if place_obj else 90)
        )
        t_mode = normalize_transit_mode(str(raw_action.get("transit_mode") or "METRO"))
        item_id = raw_action.get("item_id")

        if act_type == "REMOVE_VISIT":
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
        elif place_obj is not None:
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
            )
            sug_dicts = [
                SuggestedSlotSchema(**s.to_dict()).model_dump(mode="json")
                for s in val_res.suggested_slots
            ]
            if not val_res.valid:
                reply_text = (
                    f"Le créneau demandé ({v_date_str} à {v_time_str}) pour « {place_obj.name} » "
                    f"ne respecte pas les règles du séjour : {val_res.message}"
                )
                if sug_dicts:
                    first_s = sug_dicts[0]
                    reply_text += (
                        f" Je vous suggère plutôt le {first_s['local_date']} de "
                        f"{first_s['local_start_time']} à {first_s['local_end_time']}."
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
                "validated_by_engine": val_res.valid,
                "validation_error_code": val_res.reason_code if not val_res.valid else None,
                "validation_message_fr": val_res.message if not val_res.valid else None,
                "suggested_slots": sug_dicts,
            }
            action_status = "PENDING_CONFIRMATION"

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
            detail_fr=f"La visite « {action.get('place_name')} » a bien été retirée de votre programme.",
        )

    place = await db.scalar(
        select(Place).where(Place.id == place_id, Place.destination_id == destination.id)
    )
    if not place:
        raise HTTPException(status_code=404, detail="Lieu introuvable pour cette destination.")

    v_date = override_visit_date or date.fromisoformat(str(action["visit_date"]))
    v_time = override_local_start_time or str(action["local_start_time"])
    req_start_utc, req_end_utc = parse_local_slot_to_utc(
        visit_date=v_date,
        local_start_time_str=v_time,
        duration_minutes=dur_min,
        timezone_name=dest_tz,
    )

    existing_items, places_map = await _load_trip_items_with_places(db, trip.id)
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
    )
    if not val_res.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": val_res.reason_code,
                "message": val_res.message,
                "suggested_slots": [
                    SuggestedSlotSchema(**s.to_dict()).model_dump(mode="json")
                    for s in val_res.suggested_slots
                ],
            },
        )

    if act_type == "MOVE_VISIT" and item_id:
        target_item = await db.scalar(
            select(ItineraryItem).where(ItineraryItem.id == item_id, ItineraryItem.trip_id == trip.id)
        )
        if not target_item:
            raise HTTPException(status_code=404, detail="Visite à déplacer introuvable.")
        target_item.visit_date = v_date
        target_item.start_at = req_start_utc
        target_item.end_at = req_end_utc
        target_item.duration_minutes = dur_min
        target_item.transit_mode_to_next = t_mode
        msg.action_status = "CONFIRMED"
        await db.commit()
        await _recompute_trip_day_transits(db, trip.id, dest_tz)
        await _sync_item_with_google_calendar(db, target_item, place, dest_tz, action="update")
        return ChatActionDecisionResponse(
            message=_serialize_chat_message(msg),
            applied_change=True,
            updated_item=_to_item_response(target_item, place, dest_tz),
            deleted_item_id=None,
            detail_fr=f"Visite « {place.name} » déplacée au {v_date.isoformat()} à {v_time}.",
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
        detail_fr=f"Visite « {place.name} » ajoutée le {v_date.isoformat()} à {v_time}.",
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
