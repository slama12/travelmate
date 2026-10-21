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


class UsefulPhraseSchema(BaseModel):
    french: str
    local_translation: str
    pronunciation: str
    context_fr: str = "Vie courante"


class PracticalInfoResponse(BaseModel):
    destination_id: str
    city_name: str
    country_name: str
    target_language: str
    plugs: str
    tipping: str
    emergency: str
    dial_code: str
    currency: str
    source: str
    updated_at_fr: str
    useful_phrases: list[UsefulPhraseSchema]


class TranslateRequest(BaseModel):
    """Formulaire du traducteur (2 champs maximum <= 4 champs)."""

    text: str = Field(..., min_length=1, max_length=500)
    target_language: str | None = Field(default=None, max_length=80)


class TranslateResponse(BaseModel):
    destination_id: str
    city_name: str
    target_language: str
    source_text: str
    translated_text: str
    translation: str = ""
    pronunciation: str
    mode: str = "SIMULATED_DETERMINISTIC"
    provider_label_fr: str = "Traducteur de voyage déterministe"


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
