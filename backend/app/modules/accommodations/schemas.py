from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class NearbyRestaurantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    latitude: float
    longitude: float
    estimated_cost: Decimal
    price_tier: str
    avg_rating: float
    hero_photos: list[str] = Field(default_factory=list)
    distance_km: float
    distance_m: int
    walking_minutes: int


class AccommodationSearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    destination_id: str
    type: str
    source: str
    source_provider: str
    source_label: str
    provider_mode: str
    is_simulated: bool
    name: str
    neighborhood: str
    address: str
    latitude: float
    longitude: float
    distance_from_center_km: float
    price_per_night: Decimal
    currency: str = "EUR"
    luxury_tier: str
    rating: float
    photos: list[str] = Field(default_factory=list)
    amenities: list[str] = Field(default_factory=list)
    booking_redirect_url: str
    nearby_restaurants: list[NearbyRestaurantResponse] = Field(default_factory=list)
    external_entity_id: str | None = None
    wikidata_id: str | None = None
    photo_file_title: str | None = None
    photo_author: str | None = None
    photo_license: str | None = None
    photo_commons_url: str | None = None
    photo_source: str = "none"
    photo_credit_text: str | None = None
    accommodation_subtype: str = "hôtel"
    is_illustration: bool = False
    illustration_label: str | None = None
    price_label: str = "Prix indicatif"
    gamme_label: str = "Standard"
    has_precise_coords: bool = True
    booking_url: str | None = None
    airbnb_url: str | None = None
