from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.database import AsyncSession, get_db
from app.models.entities import Destination
from app.modules.destinations.schemas import DestinationResolveRequest, DestinationResponse

router = APIRouter(prefix="/destinations", tags=["Destinations"])

WORLD_CITY_GEODATA: dict[str, dict[str, Any]] = {
    "barcelone": {
        "city_name": "Barcelone",
        "country_name": "Espagne",
        "country_code_iso2": "ES",
        "iata_code": "BCN",
        "timezone": "Europe/Madrid",
        "latitude": 41.3874,
        "longitude": 2.1686,
    },
    "barcelona": {
        "city_name": "Barcelona",
        "country_name": "Espagne",
        "country_code_iso2": "ES",
        "iata_code": "BCN",
        "timezone": "Europe/Madrid",
        "latitude": 41.3874,
        "longitude": 2.1686,
    },
    "londres": {
        "city_name": "Londres",
        "country_name": "Royaume-Uni",
        "country_code_iso2": "GB",
        "iata_code": "LHR",
        "timezone": "Europe/London",
        "latitude": 51.5072,
        "longitude": -0.1276,
    },
    "london": {
        "city_name": "London",
        "country_name": "Royaume-Uni",
        "country_code_iso2": "GB",
        "iata_code": "LHR",
        "timezone": "Europe/London",
        "latitude": 51.5072,
        "longitude": -0.1276,
    },
    "lisbonne": {
        "city_name": "Lisbonne",
        "country_name": "Portugal",
        "country_code_iso2": "PT",
        "iata_code": "LIS",
        "timezone": "Europe/Lisbon",
        "latitude": 38.7223,
        "longitude": -9.1393,
    },
    "kyoto": {
        "city_name": "Kyoto",
        "country_name": "Japon",
        "country_code_iso2": "JP",
        "iata_code": "KIX",
        "timezone": "Asia/Tokyo",
        "latitude": 35.0116,
        "longitude": 135.7681,
    },
    "reykjavik": {
        "city_name": "Reykjavik",
        "country_name": "Islande",
        "country_code_iso2": "IS",
        "iata_code": "KEF",
        "timezone": "Atlantic/Reykjavik",
        "latitude": 64.1466,
        "longitude": -21.9426,
    },
}


@router.get("", response_model=list[DestinationResponse])
async def list_destinations(
    q: str | None = Query(default=None, description="Filtre optionnel par nom de ville ou code IATA"),
    db: AsyncSession = Depends(get_db),
) -> list[DestinationResponse]:
    stmt = select(Destination).order_by(Destination.city_name.asc())
    result = await db.scalars(stmt)
    items = list(result.all())
    if q:
        q_low = q.strip().lower()
        items = [
            d
            for d in items
            if q_low in d.city_name.lower()
            or q_low in d.country_name.lower()
            or q_low == d.iata_code.lower()
        ]
    return [DestinationResponse.model_validate(d) for d in items]


@router.post("/resolve", response_model=DestinationResponse, status_code=status.HTTP_200_OK)
async def resolve_or_create_world_destination(
    payload: DestinationResolveRequest,
    db: AsyncSession = Depends(get_db),
) -> DestinationResponse:
    """Résout une ville existante ou crée dynamiquement n'importe quelle ville du monde."""
    normalized_name = payload.city_name.strip()
    existing = await db.scalar(
        select(Destination).where(func.lower(Destination.city_name) == normalized_name.lower())
    )
    if existing:
        return DestinationResponse.model_validate(existing)

    preset = WORLD_CITY_GEODATA.get(normalized_name.lower(), {})
    iata = (
        payload.iata_code.upper()
        if payload.iata_code
        else preset.get("iata_code") or normalized_name[:3].upper()
    )
    lat = payload.latitude if payload.latitude is not None else preset.get("latitude", 46.2044)
    lng = payload.longitude if payload.longitude is not None else preset.get("longitude", 6.1432)
    country = preset.get("country_name", payload.country_name)
    iso2 = preset.get("country_code_iso2", payload.country_code_iso2.upper())
    tz = preset.get("timezone", payload.timezone)

    new_dest = Destination(
        city_name=preset.get("city_name", normalized_name),
        country_name=country,
        country_code_iso2=iso2,
        iata_code=iata,
        timezone=tz,
        latitude=float(lat),
        longitude=float(lng),
        hero_image_url="https://images.unsplash.com/photo-1488646953014-85cb44e25828?auto=format&fit=crop&w=1400&q=80",
        description=f"Destination mondiale {normalized_name} ({country}) configurée dynamiquement.",
        practical_info={
            "visa": "Vérifier les conditions d'entrée consulaires selon votre nationalité.",
            "monnaie": "Devise locale / EUR",
            "urgences": "112 / 911",
        },
        useful_phrases=[],
    )
    db.add(new_dest)
    await db.commit()
    await db.refresh(new_dest)
    return DestinationResponse.model_validate(new_dest)


@router.get("/{destination_id}", response_model=DestinationResponse)
async def get_destination(
    destination_id: str,
    db: AsyncSession = Depends(get_db),
) -> DestinationResponse:
    dest = await db.scalar(select(Destination).where(Destination.id == destination_id))
    if not dest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination introuvable.",
        )
    return DestinationResponse.model_validate(dest)
