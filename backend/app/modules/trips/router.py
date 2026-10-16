from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.database import AsyncSession, get_db
from app.models.entities import Destination, Trip, TripMember, User
from app.models.enums import InviteStatus, MemberRole, TripStatus
from app.modules.auth.router import get_current_user
from app.modules.trips.schemas import TripCreateRequest, TripResponse

router = APIRouter(prefix="/trips", tags=["Séjours (Trips)"])


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
    await db.commit()
    await db.refresh(trip)
    return TripResponse.model_validate(trip)


@router.get("", response_model=list[TripResponse])
async def list_my_trips(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TripResponse]:
    result = await db.scalars(
        select(Trip).where(Trip.owner_id == current_user.id).order_by(Trip.created_at.desc())
    )
    return [TripResponse.model_validate(t) for t in result.all()]


@router.get("/{trip_id}", response_model=TripResponse)
async def get_trip(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripResponse:
    trip = await db.scalar(
        select(Trip).where(Trip.id == trip_id, Trip.owner_id == current_user.id)
    )
    if not trip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Séjour introuvable.")
    return TripResponse.model_validate(trip)
