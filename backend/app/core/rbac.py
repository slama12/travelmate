from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select

from app.core.database import AsyncSession
from app.models.entities import Destination, Trip, TripMember
from app.models.enums import InviteStatus, MemberRole

READ_ROLES: frozenset[str] = frozenset(
    {MemberRole.OWNER.value, MemberRole.EDITOR.value, MemberRole.VIEWER.value}
)
WRITE_ROLES: frozenset[str] = frozenset({MemberRole.OWNER.value, MemberRole.EDITOR.value})
OWNER_ROLES: frozenset[str] = frozenset({MemberRole.OWNER.value})

ROLE_LABELS_FR: dict[str, str] = {
    MemberRole.OWNER.value: "Propriétaire",
    MemberRole.EDITOR.value: "Éditeur",
    MemberRole.VIEWER.value: "Lecteur",
}


def normalize_member_role(raw_role: str) -> str:
    cleaned = (raw_role or "").strip().upper()
    mapping = {
        "OWNER": MemberRole.OWNER.value,
        "PROPRIETAIRE": MemberRole.OWNER.value,
        "PROPRIÉTAIRE": MemberRole.OWNER.value,
        "EDITOR": MemberRole.EDITOR.value,
        "EDITEUR": MemberRole.EDITOR.value,
        "ÉDITEUR": MemberRole.EDITOR.value,
        "VIEWER": MemberRole.VIEWER.value,
        "LECTEUR": MemberRole.VIEWER.value,
        "READER": MemberRole.VIEWER.value,
    }
    if cleaned not in mapping:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Rôle inconnu '{raw_role}'. Valeurs acceptées : OWNER (Propriétaire), EDITOR (Éditeur), VIEWER (Lecteur).",
        )
    return mapping[cleaned]


async def get_user_trip_role(
    db: AsyncSession,
    trip: Trip,
    user_id: str,
) -> str | None:
    if trip.owner_id == user_id:
        return MemberRole.OWNER.value
    member = await db.scalar(
        select(TripMember).where(
            TripMember.trip_id == trip.id,
            TripMember.user_id == user_id,
            TripMember.invite_status == InviteStatus.ACCEPTED.value,
        )
    )
    if not member:
        return None
    return normalize_member_role(member.role)


async def require_trip_access(
    db: AsyncSession,
    trip_id: str,
    user_id: str,
    *,
    allowed_roles: frozenset[str] = READ_ROLES,
) -> tuple[Trip, Destination, str]:
    trip = await db.scalar(select(Trip).where(Trip.id == trip_id))
    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voyage introuvable.",
        )

    user_role = await get_user_trip_role(db, trip, user_id)
    if user_role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé : vous n'êtes pas membre de ce voyage.",
        )

    if user_role not in allowed_roles:
        role_label = ROLE_LABELS_FR.get(user_role, user_role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Accès refusé : votre rôle ({role_label}) est en lecture seule ou insuffisant "
                "pour effectuer cette modification."
            ),
        )

    destination = await db.scalar(select(Destination).where(Destination.id == trip.destination_id))
    if not destination:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination introuvable.",
        )

    return trip, destination, user_role
