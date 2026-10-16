from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DestinationResolveRequest(BaseModel):
    city_name: str = Field(..., min_length=2, max_length=120)
    country_name: str = Field(default="Monde", min_length=2, max_length=120)
    country_code_iso2: str = Field(default="XX", min_length=2, max_length=2)
    iata_code: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str = Field(default="UTC")
    latitude: float | None = None
    longitude: float | None = None


class DestinationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    city_name: str
    country_name: str
    country_code_iso2: str
    iata_code: str
    timezone: str
    latitude: float
    longitude: float
    hero_image_url: str
    description: str
    practical_info: dict[str, Any]
    useful_phrases: list[dict[str, Any]]
