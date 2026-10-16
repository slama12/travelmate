from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FlightOfferResponse(BaseModel):
    offer_id: str
    airline_code: str
    airline_name: str
    flight_number_outbound: str
    flight_number_inbound: str
    origin_iata: str
    destination_iata: str
    destination_city: str
    departure_outbound_at: datetime
    arrival_outbound_at: datetime
    departure_inbound_at: datetime
    arrival_inbound_at: datetime
    cabin_class: str
    price_amount: Decimal
    price_eur: float
    currency: str = "EUR"
    mode: str


class FlightBookingRequest(BaseModel):
    trip_id: str
    idempotency_key: str = Field(..., min_length=4, max_length=100)
    airline: str = Field(..., min_length=2, max_length=100)
    flight_number_outbound: str = Field(..., min_length=2, max_length=20)
    flight_number_inbound: str = Field(..., min_length=2, max_length=20)
    origin_iata: str = Field(..., min_length=3, max_length=3)
    destination_iata: str = Field(..., min_length=3, max_length=3)
    departure_outbound_at: datetime
    arrival_outbound_at: datetime
    departure_inbound_at: datetime
    arrival_inbound_at: datetime
    price_amount: Decimal = Field(..., gt=Decimal("0.00"))
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    cabin_class: str = Field(default="ECONOMY")
    passenger_name: str | None = None
    recipient_email: str | None = None

    @model_validator(mode="after")
    def validate_dates_and_airports(self) -> "FlightBookingRequest":
        if self.origin_iata.upper() == self.destination_iata.upper():
            raise ValueError("Les aéroports de départ et d'arrivée doivent être distincts.")
        if self.arrival_outbound_at <= self.departure_outbound_at:
            raise ValueError("L'arrivée du vol aller doit être strictement postérieure au départ aller.")
        if self.departure_inbound_at <= self.arrival_outbound_at:
            raise ValueError("Le départ du vol retour doit être strictement postérieur à l'arrivée du vol aller.")
        if self.arrival_inbound_at <= self.departure_inbound_at:
            raise ValueError("L'arrivée du vol retour doit être strictement postérieure au départ retour.")
        self.price_amount = self.price_amount.quantize(Decimal("0.01"))
        self.currency = self.currency.upper()
        self.origin_iata = self.origin_iata.upper()
        self.destination_iata = self.destination_iata.upper()
        return self


class FlightBookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    idempotency_key: str
    idempotent_replay: bool = False
    pnr_reference: str
    airline: str
    flight_number_outbound: str
    flight_number_inbound: str
    origin_iata: str
    destination_iata: str
    departure_outbound_at: datetime
    arrival_outbound_at: datetime
    departure_inbound_at: datetime
    arrival_inbound_at: datetime
    price_amount: Decimal
    currency: str
    cabin_class: str
    flight_status: str
    vault_document_id: str | None
    budget_item_id: str | None
    gmail_confirmation_sent: bool
    gmail_send_status: str = "SENT"
    gmail_send_attempts: int = 1
    gmail_last_error: str | None = None
    gmail_message_id: str | None
    confirmation_email_preview: dict[str, Any]
    trip_arrival_at: datetime
    trip_departure_at: datetime
    transaction_steps: dict[str, bool]
