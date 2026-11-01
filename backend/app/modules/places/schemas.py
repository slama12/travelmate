from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    destination_id: str
    city_name: str
    name: str
    description: str
    category: str
    is_outdoor: bool
    latitude: float
    longitude: float
    recommended_duration_min: int
    estimated_cost: Decimal
    price_tier: str
    avg_rating: float
    opening_hours: dict[str, Any] = Field(default_factory=dict)
    hero_photos: list[str] = Field(default_factory=list)
    photo_status: str = "Photo bientôt disponible"
    source_provider: str = "simulated"
    external_place_id: str | None = None
    address: str | None = None
    website_url: str | None = None
    price_label: str | None = None
    hours_status: str | None = None
    source_url: str | None = None
    source_attribution: str | None = None
    notoriety_score: int = 0
    photo_file_title: str | None = None
    photo_author: str | None = None
    photo_license: str | None = None
    photo_commons_url: str | None = None
    photo_source: str | None = None
    photo_credit_text: str | None = None
    photo_checked: bool = False
    is_wishlisted: bool = False
    is_selected_for_trip: bool = False


class CityPlacesResultResponse(BaseModel):
    city_name: str
    provider_mode: str
    cached_in_redis: bool = False
    available_in_current_mode: bool = True
    message: str | None = None
    few_places_message: str | None = None
    can_expand_radius: bool = False
    suggested_radius_km: int | None = None
    radius_km: int = 10
    outage_message: str | None = None
    places: list[PlaceResponse] = Field(default_factory=list)


class TripGalleryResponse(BaseModel):
    trip_id: str
    stage_id: str | None = None
    order_index: int | None = None
    city_name: str
    unlocked: bool
    unlock_message: str
    provider_mode: str
    cached_in_redis: bool = False
    few_places_message: str | None = None
    can_expand_radius: bool = False
    suggested_radius_km: int | None = None
    radius_km: int = 10
    outage_message: str | None = None
    selected_place_ids: list[str] = Field(default_factory=list)
    places: list[PlaceResponse] = Field(default_factory=list)


class TripPlaceSelectionRequest(BaseModel):
    place_id: str
    stage_id: str | None = None
    selected: bool = True


class WishlistToggleRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=300)


class WishlistToggleResponse(BaseModel):
    place_id: str
    wishlisted: bool
    notes: str | None = None
    total_wishlist_count: int
