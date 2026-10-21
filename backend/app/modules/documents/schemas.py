from datetime import date
from pydantic import BaseModel, ConfigDict, Field, field_validator


DOC_TYPE_INPUT_MAP: dict[str, str] = {
    "PASSPORT": "PASSPORT",
    "PASSEPORT": "PASSPORT",
    "FLIGHT_TICKET": "FLIGHT_TICKET",
    "BILLET": "FLIGHT_TICKET",
    "BILLET D'AVION": "FLIGHT_TICKET",
    "VOL": "FLIGHT_TICKET",
    "HOTEL_VOUCHER": "HOTEL_VOUCHER",
    "HOTEL_BOOKING": "HOTEL_VOUCHER",
    "VOUCHER": "HOTEL_VOUCHER",
    "HEBERGEMENT": "HOTEL_VOUCHER",
    "HÉBERGEMENT": "HOTEL_VOUCHER",
    "HOTEL": "HOTEL_VOUCHER",
    "INSURANCE": "INSURANCE",
    "ASSURANCE": "INSURANCE",
    "QR_CODE": "QR_CODE",
    "OTHER": "OTHER",
    "AUTRE": "OTHER",
}

DOC_TYPE_LABELS_FR: dict[str, str] = {
    "PASSPORT": "Passeport",
    "FLIGHT_TICKET": "Billet d'avion",
    "HOTEL_VOUCHER": "Réservation d'hébergement",
    "HOTEL_BOOKING": "Réservation d'hébergement",
    "INSURANCE": "Assurance voyage",
    "QR_CODE": "Billet d'entrée",
    "OTHER": "Autre document",
}


def normalize_doc_type(raw_type: str) -> str:
    key = (raw_type or "OTHER").strip().upper()
    if key in DOC_TYPE_INPUT_MAP:
        return DOC_TYPE_INPUT_MAP[key]
    raise ValueError(
        f"Catégorie de document invalide : {raw_type!r}. "
        "Valeurs autorisées : PASSPORT, FLIGHT_TICKET, HOTEL_VOUCHER, INSURANCE, OTHER."
    )


class DocumentCreateRequest(BaseModel):
    """Formulaire d'ajout de document (strictement 4 champs maximum)."""

    title: str = Field(..., min_length=2, max_length=255)
    doc_type: str = Field(default="PASSPORT", min_length=2, max_length=50)
    content_text: str = Field(..., min_length=2, max_length=8000)
    expires_on: date | None = None

    @field_validator("doc_type")
    @classmethod
    def _validate_doc_type(cls, v: str) -> str:
        return normalize_doc_type(v)


class DocumentShareUpdateRequest(BaseModel):
    is_shared: bool


class DocumentSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    owner_id: str
    is_owner: bool
    is_shared: bool
    doc_type: str
    doc_type_label_fr: str
    title: str
    mime_type: str
    checksum_sha256: str
    encrypted_at_rest: bool = True
    expires_on_fr: str | None = None
    expiration_warning: bool = False
    expiration_message_fr: str | None = None
    created_at_fr: str


class DocumentDecryptedResponse(DocumentSummaryResponse):
    decrypted_content: str
    content_text: str = ""


class TripDocumentsListResponse(BaseModel):
    trip_id: str
    destination_city: str
    current_user_role: str
    passport_expiration_alert: bool
    passport_alert_message_fr: str | None = None
    documents: list[DocumentSummaryResponse]
