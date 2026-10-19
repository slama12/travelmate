from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.itinerary.schemas import ItineraryItemResponse, SuggestedSlotSchema


# ==============================================================================
# 1. MÉTÉO & ALERTES VISITES EXTÉRIEURES
# ==============================================================================
class DailyWeatherForecastSchema(BaseModel):
    date: str
    available: bool = True
    condition_code: str
    summary: str
    precipitation_probability: int | None = None
    is_rainy: bool = False
    temperature_celsius: float | None = None
    badge_label: str


class WeatherAdaptationOptionSchema(BaseModel):
    option_id: str
    suggestion_type: Literal["INDOOR_PLACE", "ALTERNATE_SLOT"]
    label_fr: str
    replacement_place_id: str
    replacement_place_name: str
    replacement_place_category: str
    is_outdoor: bool
    visit_date: date
    local_start_time: str
    local_end_time: str
    start_at: datetime
    end_at: datetime
    duration_minutes: int
    validated_by_engine: bool = True


class WeatherVisitAlertSchema(BaseModel):
    item_id: str
    place_id: str
    place_name: str
    visit_date: str
    local_start_time: str
    local_end_time: str
    weather_condition_code: str
    weather_summary: str
    precipitation_probability: int | None = None
    alert_message_fr: str
    options: list[WeatherAdaptationOptionSchema]


class TripWeatherResponse(BaseModel):
    trip_id: str
    destination_city: str
    destination_timezone: str
    provider_mode: str
    forecast_horizon_days: int
    cache_hit: bool
    cache_backend: str
    persisted_changes: bool = False
    days: list[DailyWeatherForecastSchema]
    alerts: list[WeatherVisitAlertSchema]


class AcceptWeatherAlertRequest(BaseModel):
    replacement_place_id: str
    visit_date: date
    local_start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    duration_minutes: int = Field(default=90, ge=15, le=720)
    transit_mode: str = Field(default="METRO")


# ==============================================================================
# 2. ITINÉRAIRE IA ("GÉNÈRE MON PROGRAMME") — 4 CHAMPS MAX, BROUILLON NON PERSISTÉ
# ==============================================================================
class AIModelRawSlotSchema(BaseModel):
    """Schéma Pydantic strict pour valider le JSON brut renvoyé par le modèle IA."""

    place_id: str = Field(..., min_length=1)
    place_name: str | None = None
    visit_date: date
    local_start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    duration_minutes: int = Field(default=90, ge=15, le=720)
    transit_mode: str = Field(default="METRO")
    rationale_fr: str = Field(default="")


class AIModelRawPlanSchema(BaseModel):
    """Réponse JSON complète attendue du modèle IA."""

    summary_fr: str = Field(..., min_length=3)
    pace: Literal["RELAX", "NORMAL", "INTENSE"] = "NORMAL"
    slots: list[AIModelRawSlotSchema] = Field(..., min_length=1)


class AIGenerateItineraryRequest(BaseModel):
    """Formulaire à 3 champs (<= 4 champs maximum) : budget, rythme, goûts."""

    budget_eur: float = Field(default=1500.0, gt=0, description="Budget global estimé en euros")
    pace: Literal["RELAX", "NORMAL", "INTENSE"] = Field(
        default="NORMAL",
        description="Rythme souhaité : RELAX, NORMAL ou INTENSE",
    )
    tastes: list[str] = Field(
        default_factory=lambda: ["CULTURE", "NATURE", "FOOD"],
        max_length=4,
        description="Goûts parmi CULTURE, NATURE, FOOD, NUIT",
    )
    allow_outdoor_in_rain: bool = Field(
        default=False,
        description="Autoriser les lieux en plein air un jour d'orage ou de pluie si demandé explicitement",
    )


class AIDraftSlotSchema(BaseModel):
    place_id: str
    place_name: str
    place_category: str
    is_outdoor: bool
    visit_date: date
    visit_date_label_fr: str = ""
    local_start_time: str
    local_end_time: str
    start_at: datetime
    end_at: datetime
    duration_minutes: int
    estimated_cost_eur: float
    transit_mode: str
    transit_from_prev_min: int = 0
    transit_distance_from_prev_m: int = 0
    transit_time_source: str = "ESTIMATED"
    transit_source_label: str = "Temps estimé"
    transit_label_fr: str | None = None
    weather_summary: str = ""
    weather_adapted: bool = False
    validation_status: Literal["VALID", "CORRECTED"] = "VALID"
    adjustment_note_fr: str | None = None
    validated_by_engine: bool = True


class AIGenerateItineraryDraftResponse(BaseModel):
    trip_id: str
    destination_city: str
    destination_timezone: str
    persisted: bool = False
    calendar_synced: bool = False
    requires_user_confirmation: bool = True
    attempts_used: int = 1
    summary_fr: str
    pace: str
    budget_eur: float
    tastes: list[str]
    total_estimated_cost_eur: float
    total_transit_minutes: int
    routing_source_label: str
    limited_places_notice_fr: str | None = None
    adjustments_fr: list[str]
    draft_items: list[AIDraftSlotSchema]


class AIApplyDraftSlotInput(BaseModel):
    place_id: str
    visit_date: date
    local_start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    duration_minutes: int = Field(..., ge=15, le=720)
    transit_mode: str = "METRO"


class AIApplyDraftRequest(BaseModel):
    draft_items: list[AIApplyDraftSlotInput] = Field(..., min_length=1)
    replace_existing: bool = True


# ==============================================================================
# 3. ASSISTANT DE CHAT CONTEXTUEL & SÉCURISÉ
# ==============================================================================
class ChatProposedActionSchema(BaseModel):
    action_type: Literal["ADD_VISIT", "MOVE_VISIT", "REMOVE_VISIT"]
    item_id: str | None = None
    place_id: str
    place_name: str
    visit_date: str
    local_start_time: str
    local_end_time: str | None = None
    duration_minutes: int = 90
    transit_mode: str = "METRO"
    allow_duplicate: bool = False
    validated_by_engine: bool = True
    validation_error_code: str | None = None
    validation_message_fr: str | None = None
    suggested_slots: list[SuggestedSlotSchema] = Field(default_factory=list)


class ChatMessageResponse(BaseModel):
    id: str
    trip_id: str
    role: Literal["user", "assistant"]
    content: str
    proposed_action: ChatProposedActionSchema | None = None
    action_status: Literal["NONE", "PENDING_CONFIRMATION", "CONFIRMED", "REJECTED"] = "NONE"
    created_at: datetime


class ChatSendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1200)


class ChatConversationResponse(BaseModel):
    trip_id: str
    destination_city: str
    messages: list[ChatMessageResponse]
    security_audit: dict[str, Any]


class ChatActionDecisionResponse(BaseModel):
    message: ChatMessageResponse
    applied_change: bool
    updated_item: ItineraryItemResponse | None = None
    deleted_item_id: str | None = None
    detail_fr: str
