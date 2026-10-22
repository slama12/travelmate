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
# 3. ASSISTANT DE CHAT CONTEXTUEL & SÉCURISÉ + ACCESSIBILITÉ VOCALE (ÉTAPE 5V)
# ==============================================================================
class ChatProposedActionSchema(BaseModel):
    action_type: Literal[
        "ADD_VISIT",
        "MOVE_VISIT",
        "REMOVE_VISIT",
        "BOOK_RESERVATION",
        "PROCESS_PAYMENT",
    ]
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
    requires_double_confirmation: bool = False
    confirmation_steps_required: int = 1
    confirmation_step: int = 1
    spoken_summary_fr: str | None = None
    place_similarity_score: float | None = None
    explicit_date: bool = False
    explicit_time: bool = False
    executed_directly: bool = False
    undo_available: bool = False
    undo_window_seconds: int = 30
    undo_snapshot: dict[str, Any] | None = None


class ChatMessageResponse(BaseModel):
    id: str
    trip_id: str
    role: Literal["user", "assistant"]
    content: str
    proposed_action: ChatProposedActionSchema | None = None
    action_status: Literal[
        "NONE",
        "PENDING_CONFIRMATION",
        "AWAITING_SECOND_CONFIRMATION",
        "CONFIRMED",
        "EXECUTED_DIRECTLY",
        "UNDONE",
        "REJECTED",
    ] = "NONE"
    navigation_target: str | None = None
    voice_command: str | None = None
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


VoiceSignalType = Literal[
    "SPEECH",
    "SILENCE",
    "NOISE",
    "MIC_DENIED",
    "BROWSER_UNSUPPORTED",
    "UNRECOGNIZED_SPEECH",
]


class VoiceCommandRequest(BaseModel):
    transcript: str | None = Field(default=None, max_length=1200)
    signal: VoiceSignalType = "SPEECH"
    provider: Literal["web_speech", "whisper_local"] | None = None
    hands_free: bool = False
    execute_without_confirmation: bool = False
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)
    audio_base64: str | None = None


class VoiceCommandResponse(BaseModel):
    ok: bool
    status: str = "OK"
    trip_id: str
    provider_id: str
    provider_used: str = ""
    provider_label_fr: str
    language: str = "fr-FR"
    transits_browser_service: bool
    privacy_notice_fr: str
    hands_free: bool = False
    execute_without_confirmation: bool = False
    editable_before_send: bool = True
    auto_submitted: bool = False
    signal: str
    error_code: str | None = None
    error_message_fr: str | None = None
    recognized_transcript: str = ""
    action_type: str = "NONE"
    voice_command: str | None = None
    navigation_target: str | None = None
    day_number: int | None = None
    spoken_reply_fr: str
    requires_voice_confirmation: bool = False
    requires_confirmation: bool = False
    requires_double_confirmation: bool = False
    confirmation_steps_required: int = 0
    confirmation_step: int = 0
    pending_message_id: str | None = None
    message_id: str | None = None
    proposed_action: ChatProposedActionSchema | None = None
    applied_change: bool = False
    executed_directly: bool = False
    can_undo: bool = False
    undo_window_seconds: int = 0
    undo_message_id: str | None = None
    place_similarity_score: float | None = None
    has_explicit_date: bool = False
    has_explicit_time: bool = False
    updated_item: ItineraryItemResponse | None = None
    restored_item: ItineraryItemResponse | None = None
    deleted_item_id: str | None = None
    last_modification_history: dict[str, Any] | None = None
    message: ChatMessageResponse | None = None


class VoiceUndoRequest(BaseModel):
    message_id: str | None = None
    source: Literal["VOICE", "BUTTON"] = "VOICE"


class VoiceUndoResponse(BaseModel):
    ok: bool
    status: str = "UNDONE"
    trip_id: str
    message_id: str | None = None
    restored: bool = False
    operation_undone: str | None = None
    spoken_reply_fr: str
    detail_fr: str
    restored_item: ItineraryItemResponse | None = None
    deleted_item_id: str | None = None
    calendar_sync_restored: bool = False
    last_modification_history: dict[str, Any] | None = None
    message: ChatMessageResponse | None = None


class VoiceConfirmRequest(BaseModel):
    message_id: str | None = None
    transcript: str | None = Field(default=None, max_length=400)
    signal: VoiceSignalType = "SPEECH"
    provider: Literal["web_speech", "whisper_local"] | None = None
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)


class VoiceConfirmResponse(BaseModel):
    ok: bool
    status: str = "CONFIRMED"
    trip_id: str
    message_id: str | None = None
    decision: Literal[
        "CONFIRMED",
        "AWAITING_SECOND_CONFIRMATION",
        "CANCELLED_BY_NO",
        "CANCELLED_BY_SILENCE",
        "REPEAT_REQUIRED",
        "ERROR_NO_MODIFICATION",
    ]
    action_status: Literal[
        "NONE",
        "PENDING_CONFIRMATION",
        "AWAITING_SECOND_CONFIRMATION",
        "CONFIRMED",
        "EXECUTED_DIRECTLY",
        "UNDONE",
        "REJECTED",
    ]
    applied_change: bool = False
    pending_action_preserved: bool = False
    requires_double_confirmation: bool = False
    confirmation_steps_required: int = 1
    confirmation_step: int = 1
    error_code: str | None = None
    spoken_reply_fr: str
    detail_fr: str
    updated_item: ItineraryItemResponse | None = None
    deleted_item_id: str | None = None
    message: ChatMessageResponse | None = None


class VoiceProvidersConfigResponse(BaseModel):
    active_provider: dict[str, Any]
    available_providers: list[dict[str, Any]]
    supported_tts_rates: list[float] = Field(default_factory=lambda: [0.8, 1.0, 1.2, 1.5])
    default_language: str = "fr-FR"
    language: str = "fr-FR"
    hands_free_privacy_notice_fr: str = (
        "En mode mains libres avec Web Speech API, l'audio peut transiter par le service de reconnaissance "
        "vocale du navigateur. Vous pouvez sélectionner Whisper local pour un traitement hors navigateur."
    )



