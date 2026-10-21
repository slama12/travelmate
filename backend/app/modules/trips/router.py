from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select

from app.core.database import AsyncSession, get_db
from app.core.rbac import (
    OWNER_ROLES,
    READ_ROLES,
    ROLE_LABELS_FR,
    get_user_trip_role,
    normalize_member_role,
    require_trip_access,
)
from app.models.entities import Destination, Trip, TripMember, User
from app.models.enums import InviteStatus, MemberRole, TripStatus
from app.modules.auth.router import get_current_user
from app.modules.trips.schemas import (
    TripCreateRequest,
    TripMemberResponse,
    TripMemberUpsertRequest,
    TripResponse,
)

router = APIRouter(prefix="/trips", tags=["Séjours (Trips)"])


def _serialize_trip(trip: Trip, role: str = "OWNER") -> TripResponse:
    resp = TripResponse.model_validate(trip)
    resp.current_user_role = role
    return resp


@router.post("", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
async def create_trip(
    payload: TripCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripResponse:
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

    db.add(
        TripMember(
            trip_id=trip.id,
            user_id=current_user.id,
            role=MemberRole.OWNER.value,
            invite_status=InviteStatus.ACCEPTED.value,
        )
    )

    if current_user.email == "demo@travelmate.app" and payload.title.startswith("Séjour à "):
        from datetime import date
        from app.core.security import get_envelope_cipher
        from app.models.entities import BudgetItem, VaultDocument
        from app.models.enums import BudgetCategory

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
    return _serialize_trip(trip, MemberRole.OWNER.value)


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
        out.append(_serialize_trip(t, role))
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
    return _serialize_trip(trip, user_role)


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

