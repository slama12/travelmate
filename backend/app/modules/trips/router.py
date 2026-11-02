from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import delete, or_, select

from app.core.database import AsyncSession, get_db
from app.core.itinerary_validator import ensure_utc, to_destination_local
from app.core.rbac import (
    OWNER_ROLES,
    READ_ROLES,
    ROLE_LABELS_FR,
    WRITE_ROLES,
    get_user_trip_role,
    normalize_member_role,
    require_trip_access,
)
from app.models.entities import (
    BudgetItem,
    Destination,
    FlightBooking,
    ItineraryItem,
    Trip,
    TripMember,
    TripStage,
    User,
)
from app.models.enums import (
    BudgetCategory,
    InviteStatus,
    MemberRole,
    StageArrivalTransportMode,
    TripStatus,
    normalize_stage_transport_mode,
)
from app.modules.auth.router import get_current_user
from app.modules.trips.schemas import (
    TripCreateRequest,
    TripMemberResponse,
    TripMemberUpsertRequest,
    TripResponse,
    TripStageBatchUpdateRequest,
    TripStageConfirmTransportRequest,
    TripStageInput,
    TripStageReorderRequest,
    TripStageResponse,
    TripStageUpdateRequest,
    TripUpdateRequest,
)
from app.modules.trips.stages_service import (
    _default_stage_timestamps_utc,
    build_stage_transport_details,
    compute_stage_window_info,
    ensure_trip_stages,
    get_effective_departure_mode_for_stage,
    resolve_stage_destination,
    sync_trip_header_from_stages,
    validate_stages_rules,
)

router = APIRouter(prefix="/trips", tags=["Séjours (Trips)"])


def _serialize_stages_list(stages: list[TripStage]) -> list[TripStageResponse]:
    ordered = sorted(stages, key=lambda s: s.order_index)
    out: list[TripStageResponse] = []
    for idx, st in enumerate(ordered):
        win = compute_stage_window_info(ordered, idx)
        item = TripStageResponse.model_validate(st)
        dest = st.__dict__.get("destination")
        if dest is not None:
            if getattr(dest, "latitude", None) is not None and getattr(st, "_latitude", None) is None:
                item.latitude = float(dest.latitude)
            if getattr(dest, "longitude", None) is not None and getattr(st, "_longitude", None) is None:
                item.longitude = float(dest.longitude)
            item.iata_code = getattr(dest, "iata_code", None)
            item.hero_image_url = getattr(dest, "hero_image_url", None)
        item.departure_transport_mode = win["departure_transport_mode"]
        item.arrival_buffer_hours = float(win["arrival_buffer_hours"])
        item.departure_buffer_hours = float(win["departure_buffer_hours"])
        item.visit_window_start_utc = win["visit_window_start_utc"]
        item.visit_window_end_utc = win["visit_window_end_utc"]
        item.visit_window_start_local = win["visit_window_start_local"]
        item.visit_window_end_local = win["visit_window_end_local"]
        item.gallery_unlocked = bool(st.transport_unlocked)
        out.append(item)
    return out


async def _serialize_trip_async(
    db: AsyncSession,
    trip: Trip,
    role: str = "OWNER",
) -> TripResponse:
    stages = await ensure_trip_stages(db, trip)
    resp = TripResponse.model_validate(trip)
    resp.current_user_role = role
    resp.stages = _serialize_stages_list(stages)
    resp.stages_count = len(resp.stages)
    resp.is_multi_city = resp.stages_count > 1
    return resp


async def _prepare_and_validate_stage_specs(
    db: AsyncSession,
    stage_inputs: list[TripStageInput],
) -> list[dict[str, Any]]:
    if not stage_inputs:
        validate_stages_rules([])

    specs: list[dict[str, Any]] = []
    for idx, inp in enumerate(stage_inputs):
        spec: dict[str, Any] = {
            "id": inp.id,
            "destination_id": inp.destination_id,
            "geoname_id": inp.geoname_id,
            "city_name": inp.city_name,
            "country_name": inp.country_name or "Monde",
            "country_code_iso2": (inp.country_code_iso2 or "XX")[:2],
            "timezone": inp.timezone,
            "latitude": inp.latitude,
            "longitude": inp.longitude,
            "iata_code": inp.iata_code,
            "arrival_date": inp.arrival_date,
            "nights": inp.nights,
            "departure_date": inp.departure_date,
            "arrival_at": inp.arrival_at,
            "departure_at": inp.departure_at,
            "arrival_time_local": inp.arrival_time_local,
            "departure_time_local": inp.departure_time_local,
            "arrival_transport_mode": inp.arrival_transport_mode,
            "departure_transport_mode": inp.departure_transport_mode,
            "transport_unlocked": inp.transport_unlocked,
            "transport_booking_ref": inp.transport_booking_ref,
            "selected_place_ids": list(inp.selected_place_ids or []),
            "planned_budget": inp.planned_budget,
        }
        # Si destination_id est fourni sans city_name, pré-charge la destination pour les messages et l'identité de ville
        if spec["destination_id"] and not spec["city_name"]:
            dest_row = await db.scalar(
                select(Destination).where(Destination.id == str(spec["destination_id"]))
            )
            if not dest_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Destination introuvable.",
                )
            spec["city_name"] = dest_row.city_name
            spec["country_name"] = dest_row.country_name
            spec["country_code_iso2"] = dest_row.country_code_iso2
            spec["geoname_id"] = dest_row.geoname_id
            spec["timezone"] = spec["timezone"] or dest_row.timezone
        specs.append(spec)

    # Validation des règles métier (1..10 étapes, >= 1 nuit, consécutives sans trou ni chevauchement, pas 2x la même ville de suite)
    validate_stages_rules(specs)

    # Résolution complète des destinations GeoNames/DB et calcul des horodatages UTC dans le fuseau de chaque étape
    for idx, spec in enumerate(specs):
        dest = await resolve_stage_destination(db, spec)
        tz_name = str(spec.get("timezone") or dest.timezone or "UTC")
        dep_date, arr_utc, dep_utc = _default_stage_timestamps_utc(
            arrival_date=spec["arrival_date"],
            nights=int(spec["nights"]),
            tz_name=tz_name,
            explicit_arrival_at=spec.get("arrival_at"),
            explicit_departure_at=spec.get("departure_at"),
            arrival_time_local=spec.get("arrival_time_local"),
            departure_time_local=spec.get("departure_time_local"),
        )
        spec["destination_id"] = dest.id
        spec["geoname_id"] = spec.get("geoname_id") or dest.geoname_id
        spec["city_name"] = dest.city_name
        spec["country_name"] = dest.country_name
        spec["country_code_iso2"] = (dest.country_code_iso2 or "XX")[:2]
        spec["timezone"] = tz_name
        spec["departure_date"] = dep_date
        spec["arrival_at"] = arr_utc
        spec["departure_at"] = dep_utc

    # Re-vérifie l'absence de ville identique consécutive après résolution des destinations
    validate_stages_rules(specs)
    return specs



@router.post("", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
async def create_trip(
    payload: TripCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripResponse:
    if payload.stages is not None:
        specs = await _prepare_and_validate_stage_specs(db, payload.stages)
        first_spec = specs[0]
        last_spec = specs[-1]
        dest = await db.scalar(select(Destination).where(Destination.id == first_spec["destination_id"]))
        if not dest:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Destination introuvable.")

        trip = Trip(
            owner_id=current_user.id,
            destination_id=dest.id,
            title=payload.title,
            travel_style=payload.travel_style.value,
            total_budget_planned=payload.total_budget_planned,
            currency=payload.currency.upper(),
            preferences=payload.preferences,
            arrival_at=first_spec["arrival_at"],
            departure_at=last_spec["departure_at"],
            status=TripStatus.DRAFT.value,
        )
        db.add(trip)
        await db.flush()

        for idx, spec in enumerate(specs):
            arr_mode = spec["arrival_transport_mode"]
            default_unlocked = arr_mode in (StageArrivalTransportMode.VOITURE.value,)
            st = TripStage(
                trip_id=trip.id,
                order_index=idx + 1,
                destination_id=spec["destination_id"],
                geoname_id=spec["geoname_id"],
                city_name=spec["city_name"],
                country_name=spec["country_name"],
                country_code_iso2=spec["country_code_iso2"],
                arrival_date=spec["arrival_date"],
                nights=int(spec["nights"]),
                departure_date=spec["departure_date"],
                arrival_at=spec["arrival_at"],
                departure_at=spec["departure_at"],
                timezone=spec["timezone"],
                arrival_transport_mode=arr_mode,
                departure_transport_mode=spec.get("departure_transport_mode"),
                transport_unlocked=bool(
                    spec["transport_unlocked"]
                    if spec.get("transport_unlocked") is not None
                    else default_unlocked
                ),
                transport_booking_ref=spec.get("transport_booking_ref"),
                selected_place_ids=spec.get("selected_place_ids") or [],
                planned_budget=spec.get("planned_budget"),
            )
            db.add(st)
        await db.flush()
    else:
        if not payload.destination_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Veuillez préciser une destination ou une liste d'étapes.",
            )
        dest = await db.scalar(select(Destination).where(Destination.id == payload.destination_id))
        if not dest:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Destination introuvable.")

        if payload.arrival_at and payload.departure_at and payload.departure_at <= payload.arrival_at:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="La date de départ doit être postérieure à la date d'arrivée.",
            )

        trip = Trip(
            owner_id=current_user.id,
            destination_id=dest.id,
            title=payload.title,
            travel_style=payload.travel_style.value,
            total_budget_planned=payload.total_budget_planned,
            currency=payload.currency.upper(),
            preferences=payload.preferences,
            arrival_at=payload.arrival_at,
            departure_at=payload.departure_at,
            status=TripStatus.DRAFT.value,
        )
        db.add(trip)
        await db.flush()
        await ensure_trip_stages(db, trip)

    db.add(
        TripMember(
            trip_id=trip.id,
            user_id=current_user.id,
            role=MemberRole.OWNER.value,
            invite_status=InviteStatus.ACCEPTED.value,
        )
    )

    if current_user.email == "demo@travelmate.app" and payload.title.startswith("Séjour à "):
        from app.core.security import get_envelope_cipher
        from app.models.entities import VaultDocument

        stages_now = await ensure_trip_stages(db, trip)
        first_stage_id = stages_now[0].id if stages_now else None

        default_expenses = [
            (BudgetCategory.ACCOMMODATION.value, f"Hébergement sélectionné ({dest.city_name})", Decimal("660.00")),
            (BudgetCategory.ACTIVITY.value, f"Visites culturelles & billets ({dest.city_name})", Decimal("95.00")),
            (BudgetCategory.MEAL.value, "Repas & gastronomie locale", Decimal("160.00")),
            (BudgetCategory.TRANSPORT.value, "Transfert aéroport & transports sur place", Decimal("55.00")),
        ]
        for cat_code, title_fr, amt_dec in default_expenses:
            db.add(
                BudgetItem(
                    trip_id=trip.id,
                    stage_id=first_stage_id,
                    category=cat_code,
                    title=title_fr,
                    amount=amt_dec,
                    currency=trip.currency,
                    is_estimated=False,
                    metadata_json={
                        "original_amount": str(amt_dec),
                        "original_currency": trip.currency,
                        "exchange_rate": "1.0000",
                    },
                )
            )

        cipher = get_envelope_cipher()
        passport_enc = cipher.encrypt_document(
            f"Passeport biométrique n° 21FR88419 — Titulaire : {current_user.full_name} — Destination : {dest.city_name}".encode(
                "utf-8"
            )
        )
        db.add(
            VaultDocument(
                trip_id=trip.id,
                owner_id=current_user.id,
                doc_type="PASSPORT",
                title=f"Passeport biométrique — {current_user.full_name}",
                mime_type="text/plain",
                is_shared=False,
                expires_on=date(2027, 2, 18),
                encrypted_payload=passport_enc["encrypted_payload"],  # type: ignore[arg-type]
                encryption_iv=passport_enc["encryption_iv"],  # type: ignore[arg-type]
                encrypted_dek=passport_enc["encrypted_dek"],  # type: ignore[arg-type]
                checksum_sha256=str(passport_enc["checksum_sha256"]),
            )
        )

    await db.commit()
    await db.refresh(trip)
    return await _serialize_trip_async(db, trip, MemberRole.OWNER.value)


@router.get("", response_model=list[TripResponse])
async def list_my_trips(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TripResponse]:
    member_subq = (
        select(TripMember.trip_id)
        .where(
            TripMember.user_id == current_user.id,
            TripMember.invite_status == InviteStatus.ACCEPTED.value,
        )
        .scalar_subquery()
    )
    result = await db.scalars(
        select(Trip)
        .where(or_(Trip.owner_id == current_user.id, Trip.id.in_(member_subq)))
        .order_by(Trip.created_at.desc())
    )
    trips = list(result.all())
    out: list[TripResponse] = []
    for t in trips:
        role = await get_user_trip_role(db, t, current_user.id) or MemberRole.VIEWER.value
        out.append(await _serialize_trip_async(db, t, role))
    return out


@router.get("/{trip_id}", response_model=TripResponse)
async def get_trip(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripResponse:
    trip, _dest, user_role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=READ_ROLES
    )
    return await _serialize_trip_async(db, trip, user_role)


async def _apply_stages_batch_to_trip(
    db: AsyncSession,
    trip: Trip,
    stage_inputs: list[TripStageInput],
) -> list[TripStage]:
    specs = await _prepare_and_validate_stage_specs(db, stage_inputs)
    existing_stages = await ensure_trip_stages(db, trip)
    existing_by_id = {st.id: st for st in existing_stages}
    explicit_ids = {str(s["id"]) for s in specs if s.get("id") and str(s["id"]) in existing_by_id}
    used_existing_ids: set[str] = set()
    updated_stages: list[TripStage] = []

    for idx, spec in enumerate(specs):
        matched_stage: TripStage | None = None
        spec_id = str(spec["id"]) if spec.get("id") else None
        if spec_id and spec_id in existing_by_id and spec_id not in used_existing_ids:
            matched_stage = existing_by_id[spec_id]
        else:
            for cand in existing_stages:
                if (
                    cand.id not in used_existing_ids
                    and cand.id not in explicit_ids
                    and cand.destination_id == spec["destination_id"]
                ):
                    matched_stage = cand
                    break

        default_unlocked = spec["arrival_transport_mode"] == StageArrivalTransportMode.VOITURE.value
        if matched_stage is not None:
            used_existing_ids.add(matched_stage.id)
            old_arr_date = matched_stage.arrival_date
            old_dest_id = matched_stage.destination_id

            matched_stage.order_index = idx + 1
            matched_stage.destination_id = spec["destination_id"]
            matched_stage.geoname_id = spec["geoname_id"]
            matched_stage.city_name = spec["city_name"]
            matched_stage.country_name = spec["country_name"]
            matched_stage.country_code_iso2 = spec["country_code_iso2"]
            matched_stage.arrival_date = spec["arrival_date"]
            matched_stage.nights = int(spec["nights"])
            matched_stage.departure_date = spec["departure_date"]
            matched_stage.arrival_at = spec["arrival_at"]
            matched_stage.departure_at = spec["departure_at"]
            matched_stage.timezone = spec["timezone"]
            matched_stage.arrival_transport_mode = spec["arrival_transport_mode"]
            matched_stage.departure_transport_mode = spec.get("departure_transport_mode")
            if spec.get("transport_unlocked") is not None:
                matched_stage.transport_unlocked = bool(spec["transport_unlocked"])
            elif default_unlocked:
                matched_stage.transport_unlocked = True
            if spec.get("transport_booking_ref") is not None:
                matched_stage.transport_booking_ref = spec["transport_booking_ref"]
            if spec.get("selected_place_ids"):
                matched_stage.selected_place_ids = spec["selected_place_ids"]
            if spec.get("planned_budget") is not None:
                matched_stage.planned_budget = spec["planned_budget"]

            delta_days = (matched_stage.arrival_date - old_arr_date).days
            if old_dest_id == matched_stage.destination_id and delta_days != 0:
                stage_items = list(
                    (
                        await db.scalars(
                            select(ItineraryItem).where(
                                ItineraryItem.trip_id == trip.id,
                                ItineraryItem.stage_id == matched_stage.id,
                            )
                        )
                    ).all()
                )
                for item in stage_items:
                    item.visit_date = item.visit_date + timedelta(days=delta_days)
                    item.start_at = ensure_utc(item.start_at) + timedelta(days=delta_days)
                    item.end_at = ensure_utc(item.end_at) + timedelta(days=delta_days)

            updated_stages.append(matched_stage)
        else:
            st = TripStage(
                trip_id=trip.id,
                order_index=idx + 1,
                destination_id=spec["destination_id"],
                geoname_id=spec["geoname_id"],
                city_name=spec["city_name"],
                country_name=spec["country_name"],
                country_code_iso2=spec["country_code_iso2"],
                arrival_date=spec["arrival_date"],
                nights=int(spec["nights"]),
                departure_date=spec["departure_date"],
                arrival_at=spec["arrival_at"],
                departure_at=spec["departure_at"],
                timezone=spec["timezone"],
                arrival_transport_mode=spec["arrival_transport_mode"],
                departure_transport_mode=spec.get("departure_transport_mode"),
                transport_unlocked=bool(
                    spec["transport_unlocked"]
                    if spec.get("transport_unlocked") is not None
                    else default_unlocked
                ),
                transport_booking_ref=spec.get("transport_booking_ref"),
                selected_place_ids=spec.get("selected_place_ids") or [],
                planned_budget=spec.get("planned_budget"),
            )
            db.add(st)
            updated_stages.append(st)

    for old_st in existing_stages:
        if old_st.id not in used_existing_ids:
            await db.execute(
                delete(ItineraryItem).where(
                    ItineraryItem.trip_id == trip.id,
                    ItineraryItem.stage_id == old_st.id,
                )
            )
            await db.delete(old_st)

    await db.flush()
    for st in updated_stages:
        if st.__dict__.get("destination") is None or st.destination.id != st.destination_id:
            st.destination = await db.scalar(
                select(Destination).where(Destination.id == st.destination_id)
            )  # type: ignore[assignment]
    sync_trip_header_from_stages(trip, updated_stages)
    return updated_stages


@router.put("/{trip_id}", response_model=TripResponse)
@router.patch("/{trip_id}", response_model=TripResponse)
async def update_trip(
    trip_id: str,
    payload: TripUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripResponse:
    trip, _dest, user_role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    if payload.title is not None:
        trip.title = payload.title
    if payload.travel_style is not None:
        trip.travel_style = payload.travel_style.value
    if payload.total_budget_planned is not None:
        trip.total_budget_planned = payload.total_budget_planned
    if payload.currency is not None:
        trip.currency = payload.currency.upper()
    if payload.preferences is not None:
        trip.preferences = payload.preferences

    if payload.stages is not None:
        await _apply_stages_batch_to_trip(db, trip, payload.stages)
    elif (
        payload.destination_id is not None
        or payload.arrival_at is not None
        or payload.departure_at is not None
    ):
        stages = await ensure_trip_stages(db, trip)
        if len(stages) == 1:
            st0 = stages[0]
            new_dest_id = payload.destination_id or st0.destination_id
            dest_row = await db.scalar(select(Destination).where(Destination.id == new_dest_id))
            if not dest_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Destination introuvable.",
                )
            tz_name = dest_row.timezone or st0.timezone or "UTC"
            new_arr_utc = ensure_utc(payload.arrival_at) if payload.arrival_at else ensure_utc(st0.arrival_at)
            new_dep_utc = ensure_utc(payload.departure_at) if payload.departure_at else ensure_utc(st0.departure_at)
            if new_dep_utc <= new_arr_utc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="La date de retour doit être postérieure à la date d'arrivée.",
                )
            arr_local_date = to_destination_local(new_arr_utc, tz_name).date()
            dep_local_date = to_destination_local(new_dep_utc, tz_name).date()
            nights = max(1, (dep_local_date - arr_local_date).days)
            await _apply_stages_batch_to_trip(
                db,
                trip,
                [
                    TripStageInput(
                        id=st0.id,
                        destination_id=dest_row.id,
                        geoname_id=dest_row.geoname_id,
                        city_name=dest_row.city_name,
                        country_name=dest_row.country_name,
                        country_code_iso2=dest_row.country_code_iso2,
                        timezone=tz_name,
                        arrival_date=arr_local_date,
                        nights=nights,
                        departure_date=arr_local_date + timedelta(days=nights),
                        arrival_at=new_arr_utc,
                        departure_at=new_dep_utc,
                        arrival_transport_mode=st0.arrival_transport_mode,
                        departure_transport_mode=st0.departure_transport_mode,
                        transport_unlocked=st0.transport_unlocked,
                        transport_booking_ref=st0.transport_booking_ref,
                        selected_place_ids=list(st0.selected_place_ids or []),
                        planned_budget=float(st0.planned_budget) if st0.planned_budget is not None else None,
                    )
                ],
            )

    await db.commit()
    await db.refresh(trip)
    return await _serialize_trip_async(db, trip, user_role)


# ==============================================================================
# GESTION DES ÉTAPES MULTI-VILLES (Création, Lecture, Modification, Réordonnancement, Suppression)
# ==============================================================================


@router.get("/{trip_id}/stages", response_model=list[TripStageResponse])
@router.get("/{trip_id}/steps", response_model=list[TripStageResponse], include_in_schema=False)
async def list_trip_stages(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TripStageResponse]:
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=READ_ROLES
    )
    stages = await ensure_trip_stages(db, trip)
    await db.commit()
    return _serialize_stages_list(stages)


@router.post(
    "/{trip_id}/stages",
    response_model=list[TripStageResponse],
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/{trip_id}/steps",
    response_model=list[TripStageResponse],
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def add_or_create_trip_stage(
    trip_id: str,
    payload: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TripStageResponse]:
    """
    Ajoute une nouvelle étape à la suite du voyage (ou remplace la liste si {"stages": [...]} est fourni),
    en vérifiant toutes les règles métier (1..10 étapes, >=1 nuit, consécutives sans trou ni chevauchement,
    pas deux fois la même ville à la suite) et le contrôle d'accès par rôle (WRITE_ROLES).
    """
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    if "stages" in payload and isinstance(payload["stages"], list):
        batch = TripStageBatchUpdateRequest.model_validate(payload)
        return await replace_trip_stages(trip_id, batch, current_user, db)

    stage_input = TripStageInput.model_validate(payload)
    existing_stages = await ensure_trip_stages(db, trip)

    combined_inputs: list[TripStageInput] = [
        TripStageInput(
            id=st.id,
            destination_id=st.destination_id,
            geoname_id=st.geoname_id,
            city_name=st.city_name,
            country_name=st.country_name,
            country_code_iso2=st.country_code_iso2,
            timezone=st.timezone,
            arrival_date=st.arrival_date,
            nights=st.nights,
            departure_date=st.departure_date,
            arrival_at=st.arrival_at,
            departure_at=st.departure_at,
            arrival_transport_mode=st.arrival_transport_mode,
            departure_transport_mode=st.departure_transport_mode,
            transport_unlocked=st.transport_unlocked,
            transport_booking_ref=st.transport_booking_ref,
            selected_place_ids=list(st.selected_place_ids or []),
            planned_budget=float(st.planned_budget) if st.planned_budget is not None else None,
        )
        for st in existing_stages
    ]
    combined_inputs.append(stage_input)

    specs = await _prepare_and_validate_stage_specs(db, combined_inputs)
    new_spec = specs[-1]
    new_stage = TripStage(
        trip_id=trip.id,
        order_index=len(existing_stages) + 1,
        destination_id=new_spec["destination_id"],
        geoname_id=new_spec["geoname_id"],
        city_name=new_spec["city_name"],
        country_name=new_spec["country_name"],
        country_code_iso2=new_spec["country_code_iso2"],
        arrival_date=new_spec["arrival_date"],
        nights=int(new_spec["nights"]),
        departure_date=new_spec["departure_date"],
        arrival_at=new_spec["arrival_at"],
        departure_at=new_spec["departure_at"],
        timezone=new_spec["timezone"],
        arrival_transport_mode=new_spec["arrival_transport_mode"],
        departure_transport_mode=new_spec.get("departure_transport_mode"),
        transport_unlocked=bool(
            new_spec["transport_unlocked"]
            if new_spec.get("transport_unlocked") is not None
            else (new_spec["arrival_transport_mode"] == StageArrivalTransportMode.VOITURE.value)
        ),
        transport_booking_ref=new_spec.get("transport_booking_ref"),
        selected_place_ids=new_spec.get("selected_place_ids") or [],
        planned_budget=new_spec.get("planned_budget"),
    )
    db.add(new_stage)
    await db.flush()
    new_stage.destination = await db.scalar(
        select(Destination).where(Destination.id == new_stage.destination_id)
    )  # type: ignore[assignment]

    all_stages = existing_stages + [new_stage]
    sync_trip_header_from_stages(trip, all_stages)
    await db.commit()
    return _serialize_stages_list(all_stages)


@router.put("/{trip_id}/stages", response_model=list[TripStageResponse])
@router.put("/{trip_id}/steps", response_model=list[TripStageResponse], include_in_schema=False)
async def replace_trip_stages(
    trip_id: str,
    payload: TripStageBatchUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TripStageResponse]:
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    updated_stages = await _apply_stages_batch_to_trip(db, trip, payload.stages)
    await db.commit()
    return _serialize_stages_list(updated_stages)


@router.put("/{trip_id}/stages/reorder", response_model=list[TripStageResponse])
@router.patch("/{trip_id}/stages/reorder", response_model=list[TripStageResponse])
@router.post("/{trip_id}/stages/reorder", response_model=list[TripStageResponse])
@router.put("/{trip_id}/steps/reorder", response_model=list[TripStageResponse], include_in_schema=False)
@router.patch("/{trip_id}/steps/reorder", response_model=list[TripStageResponse], include_in_schema=False)
@router.post("/{trip_id}/steps/reorder", response_model=list[TripStageResponse], include_in_schema=False)
async def reorder_trip_stages(
    trip_id: str,
    payload: TripStageReorderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TripStageResponse]:
    """
    Réordonne les étapes d'un voyage, recalcule les dates consécutives sans trou ni chevauchement
    à partir de la date de début du voyage (en préservant le nombre de nuits et le fuseau de chaque étape),
    et vérifie qu'aucune ville ne se retrouve deux fois de suite.
    """
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    existing_stages = await ensure_trip_stages(db, trip)
    stage_by_id = {st.id: st for st in existing_stages}

    requested_ids = payload.stage_ids or []
    if len(requested_ids) != len(existing_stages) or set(requested_ids) != set(stage_by_id.keys()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "reason_code": "INVALID_STAGE_REORDER_IDS",
                "message": "La liste des identifiants d'étapes à réordonner doit contenir exactement toutes les étapes du voyage.",
            },
        )

    reordered_entities = [stage_by_id[sid] for sid in requested_ids]
    initial_start_date = min(st.arrival_date for st in existing_stages)

    reordered_specs: list[dict[str, Any]] = []
    cursor_date = initial_start_date
    for idx, st in enumerate(reordered_entities):
        arr_date = cursor_date if payload.recalculate_dates else st.arrival_date
        dep_date = arr_date + timedelta(days=st.nights)
        cursor_date = dep_date
        reordered_specs.append(
            {
                "stage_entity": st,
                "destination_id": st.destination_id,
                "geoname_id": st.geoname_id,
                "city_name": st.city_name,
                "country_name": st.country_name,
                "country_code_iso2": st.country_code_iso2,
                "timezone": st.timezone,
                "arrival_date": arr_date,
                "nights": st.nights,
                "departure_date": dep_date,
                "arrival_transport_mode": st.arrival_transport_mode,
                "departure_transport_mode": st.departure_transport_mode,
            }
        )

    validate_stages_rules(reordered_specs)

    for idx, spec in enumerate(reordered_specs):
        st = spec["stage_entity"]
        old_arr_date = st.arrival_date
        new_arr_date: date = spec["arrival_date"]
        delta_days = (new_arr_date - old_arr_date).days

        st.order_index = idx + 1
        st.arrival_date = new_arr_date
        st.departure_date = spec["departure_date"]
        _, new_arr_utc, new_dep_utc = _default_stage_timestamps_utc(
            arrival_date=new_arr_date,
            nights=st.nights,
            tz_name=st.timezone,
        )
        st.arrival_at = new_arr_utc
        st.departure_at = new_dep_utc

        # Décale également les visites existantes rattachées à cette étape pour qu'elles suivent la nouvelle date
        if delta_days != 0:
            stage_items = list(
                (
                    await db.scalars(
                        select(ItineraryItem).where(
                            ItineraryItem.trip_id == trip.id,
                            ItineraryItem.stage_id == st.id,
                        )
                    )
                ).all()
            )
            for item in stage_items:
                item.visit_date = item.visit_date + timedelta(days=delta_days)
                item.start_at = ensure_utc(item.start_at) + timedelta(days=delta_days)
                item.end_at = ensure_utc(item.end_at) + timedelta(days=delta_days)

    await db.flush()
    sync_trip_header_from_stages(trip, reordered_entities)
    await db.commit()
    return _serialize_stages_list(reordered_entities)


@router.put("/{trip_id}/stages/{stage_id}", response_model=list[TripStageResponse])
@router.patch("/{trip_id}/stages/{stage_id}", response_model=list[TripStageResponse])
@router.put("/{trip_id}/steps/{stage_id}", response_model=list[TripStageResponse], include_in_schema=False)
@router.patch("/{trip_id}/steps/{stage_id}", response_model=list[TripStageResponse], include_in_schema=False)
async def update_trip_stage(
    trip_id: str,
    stage_id: str,
    payload: TripStageUpdateRequest,
    recalculate_dates: bool | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TripStageResponse]:
    """
    Modifie une étape existante d'un voyage (ville, coordonnées GPS, dates d'arrivée/départ, nombre de nuits,
    mode de transport, budget), recalcule les dates des étapes suivantes si recalculate_dates=True,
    et valide toutes les règles métier (aucun trou ni chevauchement, pas deux fois la même ville à la suite).
    """
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    existing_stages = await ensure_trip_stages(db, trip)
    target_idx = next((i for i, st in enumerate(existing_stages) if st.id == stage_id), None)
    if target_idx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Étape introuvable sur ce voyage.",
        )

    effective_recalc = (
        recalculate_dates if recalculate_dates is not None else payload.recalculate_dates
    )

    stage_inputs: list[TripStageInput] = []
    running_cursor_date: date | None = None

    for idx, st in enumerate(existing_stages):
        if idx < target_idx:
            inp = TripStageInput(
                id=st.id,
                destination_id=st.destination_id,
                geoname_id=st.geoname_id,
                city_name=st.city_name,
                country_name=st.country_name,
                country_code_iso2=st.country_code_iso2,
                timezone=st.timezone,
                arrival_date=st.arrival_date,
                nights=st.nights,
                departure_date=st.departure_date,
                arrival_at=st.arrival_at,
                departure_at=st.departure_at,
                arrival_transport_mode=st.arrival_transport_mode,
                departure_transport_mode=st.departure_transport_mode,
                transport_unlocked=st.transport_unlocked,
                transport_booking_ref=st.transport_booking_ref,
                selected_place_ids=list(st.selected_place_ids or []),
                planned_budget=float(st.planned_budget) if st.planned_budget is not None else None,
            )
            stage_inputs.append(inp)
            running_cursor_date = st.departure_date
        elif idx == target_idx:
            new_arr = payload.arrival_date if payload.arrival_date is not None else st.arrival_date
            if payload.departure_date is not None and payload.nights is None:
                new_dep = payload.departure_date
                new_nights = (new_dep - new_arr).days
            elif payload.nights is not None and payload.departure_date is None:
                new_nights = payload.nights
                new_dep = new_arr + timedelta(days=max(0, new_nights))
            elif payload.nights is not None and payload.departure_date is not None:
                new_nights = payload.nights
                new_dep = payload.departure_date
            else:
                new_nights = st.nights
                new_dep = new_arr + timedelta(days=new_nights)

            city_changed = (
                (payload.city_name is not None and payload.city_name.strip().lower() != st.city_name.strip().lower())
                or (payload.geoname_id is not None and payload.geoname_id != st.geoname_id)
            )
            dest_id = (
                payload.destination_id
                if payload.destination_id is not None
                else (None if city_changed else st.destination_id)
            )
            inp = TripStageInput(
                id=st.id,
                destination_id=dest_id,
                geoname_id=payload.geoname_id if payload.geoname_id is not None else (None if city_changed else st.geoname_id),
                city_name=payload.city_name if payload.city_name is not None else st.city_name,
                country_name=payload.country_name if payload.country_name is not None else st.country_name,
                country_code_iso2=payload.country_code_iso2 if payload.country_code_iso2 is not None else st.country_code_iso2,
                timezone=payload.timezone if payload.timezone is not None else (None if city_changed else st.timezone),
                latitude=payload.latitude,
                longitude=payload.longitude,
                iata_code=payload.iata_code,
                arrival_date=new_arr,
                nights=new_nights,
                departure_date=new_dep,
                arrival_at=payload.arrival_at,
                departure_at=payload.departure_at,
                arrival_time_local=payload.arrival_time_local,
                departure_time_local=payload.departure_time_local,
                arrival_transport_mode=(
                    payload.arrival_transport_mode
                    if payload.arrival_transport_mode is not None
                    else st.arrival_transport_mode
                ),
                departure_transport_mode=(
                    payload.departure_transport_mode
                    if payload.departure_transport_mode is not None
                    else st.departure_transport_mode
                ),
                transport_unlocked=(
                    payload.transport_unlocked
                    if payload.transport_unlocked is not None
                    else st.transport_unlocked
                ),
                transport_booking_ref=(
                    payload.transport_booking_ref
                    if payload.transport_booking_ref is not None
                    else st.transport_booking_ref
                ),
                selected_place_ids=(
                    list(payload.selected_place_ids)
                    if payload.selected_place_ids is not None
                    else list(st.selected_place_ids or [])
                ),
                planned_budget=(
                    payload.planned_budget
                    if payload.planned_budget is not None
                    else (float(st.planned_budget) if st.planned_budget is not None else None)
                ),
            )
            stage_inputs.append(inp)
            running_cursor_date = new_dep
        else:
            next_arr = running_cursor_date if (effective_recalc and running_cursor_date is not None) else st.arrival_date
            next_dep = next_arr + timedelta(days=st.nights)
            running_cursor_date = next_dep
            inp = TripStageInput(
                id=st.id,
                destination_id=st.destination_id,
                geoname_id=st.geoname_id,
                city_name=st.city_name,
                country_name=st.country_name,
                country_code_iso2=st.country_code_iso2,
                timezone=st.timezone,
                arrival_date=next_arr,
                nights=st.nights,
                departure_date=next_dep,
                arrival_transport_mode=st.arrival_transport_mode,
                departure_transport_mode=st.departure_transport_mode,
                transport_unlocked=st.transport_unlocked,
                transport_booking_ref=st.transport_booking_ref,
                selected_place_ids=list(st.selected_place_ids or []),
                planned_budget=float(st.planned_budget) if st.planned_budget is not None else None,
            )
            stage_inputs.append(inp)

    updated_stages = await _apply_stages_batch_to_trip(db, trip, stage_inputs)
    if payload.latitude is not None:
        updated_stages[target_idx].latitude = payload.latitude
    if payload.longitude is not None:
        updated_stages[target_idx].longitude = payload.longitude
    await db.commit()
    return _serialize_stages_list(updated_stages)


@router.delete("/{trip_id}/stages/{stage_id}", response_model=list[TripStageResponse])
@router.delete(
    "/{trip_id}/steps/{stage_id}",
    response_model=list[TripStageResponse],
    include_in_schema=False,
)
async def delete_trip_stage(
    trip_id: str,
    stage_id: str,
    recalculate_dates: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TripStageResponse]:
    """
    Supprime une étape d'un voyage, referme automatiquement le trou de dates en décalant les étapes
    suivantes (si recalculate_dates=True), et vérifie qu'il reste au moins 1 étape et qu'aucune ville
    ne se retrouve deux fois de suite.
    """
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    existing_stages = await ensure_trip_stages(db, trip)
    target = next((st for st in existing_stages if st.id == stage_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Étape introuvable sur ce voyage.",
        )

    remaining = [st for st in existing_stages if st.id != stage_id]
    if len(remaining) < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "reason_code": "INVALID_STAGE_COUNT",
                "message": "Un voyage doit comprendre entre 1 et 10 étapes : impossible de supprimer la seule étape restante.",
            },
        )

    initial_start_date = existing_stages[0].arrival_date
    cursor_date = initial_start_date
    remaining_specs: list[dict[str, Any]] = []
    for st in remaining:
        arr_date = cursor_date if recalculate_dates else st.arrival_date
        dep_date = arr_date + timedelta(days=st.nights)
        cursor_date = dep_date
        remaining_specs.append(
            {
                "stage_entity": st,
                "destination_id": st.destination_id,
                "geoname_id": st.geoname_id,
                "city_name": st.city_name,
                "country_name": st.country_name,
                "country_code_iso2": st.country_code_iso2,
                "timezone": st.timezone,
                "arrival_date": arr_date,
                "nights": st.nights,
                "departure_date": dep_date,
                "arrival_transport_mode": st.arrival_transport_mode,
                "departure_transport_mode": st.departure_transport_mode,
            }
        )

    validate_stages_rules(remaining_specs)

    # Supprime les visites programmées sur l'étape supprimée
    await db.execute(
        delete(ItineraryItem).where(
            ItineraryItem.trip_id == trip.id,
            ItineraryItem.stage_id == target.id,
        )
    )
    await db.delete(target)
    await db.flush()

    for idx, spec in enumerate(remaining_specs):
        st = spec["stage_entity"]
        old_arr_date = st.arrival_date
        new_arr_date = spec["arrival_date"]
        delta_days = (new_arr_date - old_arr_date).days

        st.order_index = idx + 1
        st.arrival_date = new_arr_date
        st.departure_date = spec["departure_date"]
        _, new_arr_utc, new_dep_utc = _default_stage_timestamps_utc(
            arrival_date=new_arr_date,
            nights=st.nights,
            tz_name=st.timezone,
        )
        st.arrival_at = new_arr_utc
        st.departure_at = new_dep_utc

        if delta_days != 0:
            stage_items = list(
                (
                    await db.scalars(
                        select(ItineraryItem).where(
                            ItineraryItem.trip_id == trip.id,
                            ItineraryItem.stage_id == st.id,
                        )
                    )
                ).all()
            )
            for item in stage_items:
                item.visit_date = item.visit_date + timedelta(days=delta_days)
                item.start_at = ensure_utc(item.start_at) + timedelta(days=delta_days)
                item.end_at = ensure_utc(item.end_at) + timedelta(days=delta_days)

    await db.flush()
    sync_trip_header_from_stages(trip, remaining)
    await db.commit()
    return _serialize_stages_list(remaining)


@router.get("/{trip_id}/transports")
@router.get("/{trip_id}/stages/transports")
@router.get("/{trip_id}/steps/transports", include_in_schema=False)
async def list_trip_interstage_transports(
    trip_id: str,
    origin_iata: str = Query(default="CDG", min_length=3, max_length=3),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Retourne les offres et comparateurs de trajets pour chaque étape du voyage :
    - Vols (VOL) : offres d'exemple basées sur la distance OurAirports avec bandeau "Offres d'exemple, prix indicatifs".
    - Train, bus, bateau, voiture : liens de comparateurs externes sans aucun horaire ni compagnie inventés.
    """
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=READ_ROLES
    )
    stages = await ensure_trip_stages(db, trip)
    legs: list[dict[str, Any]] = []
    for idx in range(len(stages)):
        leg = await build_stage_transport_details(
            db,
            trip,
            stages,
            idx,
            default_origin_iata=origin_iata.upper(),
        )
        legs.append(leg)
    return {
        "trip_id": trip.id,
        "stages_count": len(stages),
        "transports": legs,
        "stages_transports": legs,
    }


@router.get("/{trip_id}/stages/{stage_id}/transports")
@router.get("/{trip_id}/steps/{stage_id}/transports", include_in_schema=False)
async def get_single_stage_transport_details(
    trip_id: str,
    stage_id: str,
    origin_iata: str = Query(default="CDG", min_length=3, max_length=3),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=READ_ROLES
    )
    stages = await ensure_trip_stages(db, trip)
    stage_idx = next((idx for idx, st in enumerate(stages) if st.id == stage_id), None)
    if stage_idx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Étape introuvable sur ce voyage.",
        )
    return await build_stage_transport_details(
        db,
        trip,
        stages,
        stage_idx,
        default_origin_iata=origin_iata.upper(),
    )


@router.post("/{trip_id}/stages/{stage_id}/confirm-transport", response_model=TripStageResponse)
@router.post("/{trip_id}/stages/{stage_id}/unlock-transport", response_model=TripStageResponse)
@router.post(
    "/{trip_id}/steps/{stage_id}/confirm-transport",
    response_model=TripStageResponse,
    include_in_schema=False,
)
async def confirm_stage_arrival_transport(
    trip_id: str,
    stage_id: str,
    payload: TripStageConfirmTransportRequest = Body(default_factory=TripStageConfirmTransportRequest),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripStageResponse:
    """
    Valide le trajet d'arrivée d'une étape (après réservation de vol ou confirmation de billet
    train/bus/bateau/voiture), ce qui débloque la galerie des lieux de cette étape uniquement.
    """
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    stages = await ensure_trip_stages(db, trip)
    stage_idx = next((idx for idx, st in enumerate(stages) if st.id == stage_id), None)
    if stage_idx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Étape introuvable sur ce voyage.",
        )
    stage = stages[stage_idx]
    if payload.transport_mode:
        try:
            stage.arrival_transport_mode = normalize_stage_transport_mode(payload.transport_mode)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"reason_code": "INVALID_TRANSPORT_MODE", "message": str(exc)},
            ) from exc

    stage.transport_unlocked = True
    stage.transport_booking_ref = (
        payload.booking_reference
        or stage.transport_booking_ref
        or f"{stage.arrival_transport_mode}-{stage.order_index}"
    )

    if payload.actual_cost is not None and payload.actual_cost > 0:
        db.add(
            BudgetItem(
                trip_id=trip.id,
                stage_id=stage.id,
                category=BudgetCategory.TRANSPORT.value,
                title=payload.title or f"Trajet d'arrivée ({stage.arrival_transport_mode}) — {stage.city_name}",
                planned_amount=Decimal(str(payload.actual_cost)),
                actual_amount=Decimal(str(payload.actual_cost)),
                currency=(payload.currency or trip.currency or "EUR").upper(),
            )
        )

    await db.commit()
    await db.refresh(stage)
    serialized = _serialize_stages_list(stages)
    return serialized[stage_idx]


# ==============================================================================
# MEMBRES DU VOYAGE (RBAC)
# ==============================================================================


@router.get("/{trip_id}/members", response_model=list[TripMemberResponse])
async def list_trip_members(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TripMemberResponse]:
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=READ_ROLES
    )
    members_rows = (
        await db.scalars(select(TripMember).where(TripMember.trip_id == trip.id))
    ).all()
    out: list[TripMemberResponse] = []
    seen_users: set[str] = set()
    for m in members_rows:
        u = await db.scalar(select(User).where(User.id == m.user_id))
        if not u:
            continue
        seen_users.add(u.id)
        norm_role = (
            MemberRole.OWNER.value
            if u.id == trip.owner_id
            else normalize_member_role(m.role)
        )
        out.append(
            TripMemberResponse(
                id=m.id,
                trip_id=trip.id,
                user_id=u.id,
                email=u.email,
                full_name=u.full_name,
                role=norm_role,
                role_label_fr=ROLE_LABELS_FR.get(norm_role, norm_role),
                invite_status=m.invite_status,
            )
        )
    if trip.owner_id not in seen_users:
        owner_u = await db.scalar(select(User).where(User.id == trip.owner_id))
        if owner_u:
            out.insert(
                0,
                TripMemberResponse(
                    id=f"owner-{trip.id}",
                    trip_id=trip.id,
                    user_id=owner_u.id,
                    email=owner_u.email,
                    full_name=owner_u.full_name,
                    role=MemberRole.OWNER.value,
                    role_label_fr=ROLE_LABELS_FR[MemberRole.OWNER.value],
                    invite_status=InviteStatus.ACCEPTED.value,
                ),
            )
    return out


@router.post(
    "/{trip_id}/members",
    response_model=TripMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_trip_member(
    trip_id: str,
    payload: TripMemberUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripMemberResponse:
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=OWNER_ROLES
    )
    target_role = normalize_member_role(payload.role)
    target_user: User | None = None
    if payload.user_id:
        target_user = await db.scalar(select(User).where(User.id == payload.user_id))
    elif payload.email:
        target_user = await db.scalar(
            select(User).where(User.email == payload.email.strip().lower())
        )
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable pour ce partage.",
        )

    existing = await db.scalar(
        select(TripMember).where(
            TripMember.trip_id == trip.id,
            TripMember.user_id == target_user.id,
        )
    )
    if existing:
        existing.role = target_role
        existing.invite_status = InviteStatus.ACCEPTED.value
        member_row = existing
    else:
        member_row = TripMember(
            trip_id=trip.id,
            user_id=target_user.id,
            role=target_role,
            invite_status=InviteStatus.ACCEPTED.value,
        )
        db.add(member_row)

    await db.commit()
    await db.refresh(member_row)
    return TripMemberResponse(
        id=member_row.id,
        trip_id=trip.id,
        user_id=target_user.id,
        email=target_user.email,
        full_name=target_user.full_name,
        role=target_role,
        role_label_fr=ROLE_LABELS_FR.get(target_role, target_role),
        invite_status=member_row.invite_status,
    )


@router.delete("/{trip_id}/members/{member_user_id}")
async def remove_trip_member(
    trip_id: str,
    member_user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    trip, _dest, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=OWNER_ROLES
    )
    if member_user_id == trip.owner_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le propriétaire principal du voyage ne peut pas être retiré.",
        )
    existing = await db.scalar(
        select(TripMember).where(
            TripMember.trip_id == trip.id,
            TripMember.user_id == member_user_id,
        )
    )
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membre introuvable sur ce voyage.",
        )
    await db.delete(existing)
    await db.commit()
    return {"status": "deleted", "user_id": member_user_id}
