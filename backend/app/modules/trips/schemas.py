from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TravelStyle


class TripCreateRequest(BaseModel):
    destination_id: str
    title: str = Field(min_length=2, max_length=200)
    travel_style: TravelStyle = TravelStyle.STANDARD
    total_budget_planned: float = Field(default=1500.0, ge=0.0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    preferences: dict[str, Any] = Field(default_factory=lambda: {"culture": True, "food": True})
    arrival_at: datetime | None = None
    departure_at: datetime | None = None


class TripResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    destination_id: str
    title: str
    arrival_at: datetime | None
    departure_at: datetime | None
    travel_style: str
    total_budget_planned: float
    currency: str
    preferences: dict[str, Any]
    selected_place_ids: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime
