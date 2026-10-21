from datetime import date, timezone
from decimal import Decimal
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.core.database import AsyncSession, get_db
from app.core.providers import get_provider_registry
from app.core.security import get_envelope_cipher
from app.models.entities import BudgetItem, Destination, FlightBooking, Trip, User, VaultDocument
from app.models.enums import BudgetCategory, DocumentType, FlightStatus, TripStatus
from app.modules.auth.router import get_current_user
from app.modules.flights.schemas import (
    FlightBookingRequest,
    FlightBookingResponse,
    FlightOfferResponse,
)

router = APIRouter(prefix="/flights", tags=["Flights"])


def _ensure_utc(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_booking_response(
    booking: FlightBooking,
    trip: Trip,
    *,
    idempotent_replay: bool,
    steps: dict[str, bool],
) -> FlightBookingResponse:
    price_dec = Decimal(str(booking.price)).quantize(Decimal("0.01"))
    return FlightBookingResponse(
        id=booking.id,
        trip_id=booking.trip_id,
        idempotency_key=booking.idempotency_key,
        idempotent_replay=idempotent_replay,
        pnr_reference=booking.pnr_reference,
        airline=booking.airline,
        flight_number_outbound=booking.flight_number_outbound,
        flight_number_inbound=booking.flight_number_inbound,
        origin_iata=booking.origin_iata,
        destination_iata=booking.destination_iata,
        departure_outbound_at=booking.departure_outbound_at,
        arrival_outbound_at=booking.arrival_outbound_at,
        departure_inbound_at=booking.departure_inbound_at,
        arrival_inbound_at=booking.arrival_inbound_at,
        price_amount=price_dec,
        currency=booking.currency,
        cabin_class=booking.cabin_class,
        flight_status=booking.flight_status,
        vault_document_id=booking.vault_document_id,
        budget_item_id=booking.budget_item_id,
        gmail_confirmation_sent=booking.gmail_confirmation_sent,
        gmail_send_status=booking.gmail_send_status,
        gmail_send_attempts=booking.gmail_send_attempts,
        gmail_last_error=booking.gmail_last_error,
        gmail_message_id=booking.gmail_message_id,
        confirmation_email_preview=booking.confirmation_email_preview or {},
        trip_arrival_at=trip.arrival_at or booking.arrival_outbound_at,
        trip_departure_at=trip.departure_at or booking.departure_inbound_at,
        transaction_steps=steps,
    )


async def _dispatch_confirmation_email_post_commit(
    db: AsyncSession,
    booking: FlightBooking,
    recipient_email: str,
    passenger_name: str,
    max_attempts: int = 2,
) -> bool:
    """
    Envoie l'e-mail de confirmation APRÈS le commit de la transaction de réservation.
    En cas d'échec, effectue une nouvelle tentative automatique ; si la panne persiste,
    la réservation reste engagée avec le statut 'PENDING_RETRY' sans annuler le billet.
    """
    registry = get_provider_registry()
    last_error: str | None = None
    price_float = float(Decimal(str(booking.price)).quantize(Decimal("0.01")))

    for _ in range(max_attempts):
        booking.gmail_send_attempts = (booking.gmail_send_attempts or 0) + 1
        try:
            email_result = await registry.gmail.send_booking_confirmation(
                recipient_email=recipient_email,
                passenger_name=passenger_name,
                pnr=booking.pnr_reference,
                origin_iata=booking.origin_iata,
                destination_iata=booking.destination_iata,
                departure_at=booking.departure_outbound_at,
                return_at=booking.departure_inbound_at,
                price_eur=price_float,
            )
            booking.gmail_confirmation_sent = bool(email_result.get("sent", True))
            booking.gmail_send_status = "SENT"
            booking.gmail_last_error = None
            booking.gmail_message_id = email_result.get("message_id")
            booking.confirmation_email_preview = email_result
            await db.commit()
            await db.refresh(booking)
            return True
        except Exception as exc:
            last_error = str(exc)

    booking.gmail_confirmation_sent = False
    booking.gmail_send_status = "PENDING_RETRY"
    booking.gmail_last_error = last_error
    booking.confirmation_email_preview = {
        "provider": registry.gmail.__class__.__name__,
        "mode": registry.gmail.mode,
        "recipient": recipient_email,
        "subject": f"[En attente d'envoi] Confirmation vol {booking.origin_iata} -> {booking.destination_iata} (PNR: {booking.pnr_reference})",
        "preview": (
            f"Votre réservation PNR {booking.pnr_reference} est confirmée et enregistrée. "
            f"L'envoi de l'email a échoué après {booking.gmail_send_attempts} tentative(s) ({last_error}) et sera relancé."
        ),
        "status": "PENDING_RETRY",
        "attempts": booking.gmail_send_attempts,
        "last_error": last_error,
    }
    await db.commit()
    await db.refresh(booking)
    return False


@router.get("/search", response_model=list[FlightOfferResponse])
async def search_flights(
    origin_iata: str = Query(default="CDG", min_length=3, max_length=3),
    destination_iata: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
        description="Code IATA arrivée (résolu automatiquement depuis la destination du séjour)",
    ),
    trip_id: str | None = Query(
        default=None,
        description="Identifiant du séjour pour forcer la destination du séjour",
    ),
    departure_date: date = Query(...),
    return_date: date = Query(...),
    travel_style: str = Query(default="STANDARD"),
    db: AsyncSession = Depends(get_db),
) -> list[FlightOfferResponse]:
    orig = origin_iata.upper()
    if destination_iata is not None and orig == destination_iata.upper() and trip_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Les aéroports de départ et d'arrivée doivent être distincts.",
        )
    if return_date <= departure_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La date de retour doit être strictement postérieure à la date de départ.",
        )

    resolved_dest: Destination | None = None
    effective_dest_iata: str | None = None

    if trip_id is not None:
        trip = await db.scalar(select(Trip).where(Trip.id == trip_id))
        if not trip:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Séjour introuvable.",
            )
        resolved_dest = await db.scalar(
            select(Destination).where(Destination.id == trip.destination_id)
        )
        if not resolved_dest:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Destination du séjour introuvable.",
            )
        trip_dest_iata = resolved_dest.iata_code.upper()
        if destination_iata is not None and destination_iata.upper() != trip_dest_iata:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"La destination envoyée ({destination_iata.upper()}) ne correspond pas "
                    f"à la destination du séjour ({resolved_dest.city_name} - {trip_dest_iata})."
                ),
            )
        effective_dest_iata = trip_dest_iata
    else:
        if destination_iata is not None:
            effective_dest_iata = destination_iata.upper()
            resolved_dest = await db.scalar(
                select(Destination).where(Destination.iata_code == effective_dest_iata)
            )
        else:
            active_trip = await db.scalar(
                select(Trip)
                .where(Trip.status == TripStatus.DRAFT.value)
                .order_by(Trip.created_at.desc())
                .limit(1)
            )
            if active_trip is None:
                active_trip = await db.scalar(
                    select(Trip).order_by(Trip.created_at.desc()).limit(1)
                )
            if active_trip is not None:
                trip_dest = await db.scalar(
                    select(Destination).where(Destination.id == active_trip.destination_id)
                )
                if trip_dest and trip_dest.iata_code.upper() != orig:
                    resolved_dest = trip_dest
                    effective_dest_iata = trip_dest.iata_code.upper()

            if effective_dest_iata is None:
                effective_dest_iata = "RAK"
                resolved_dest = await db.scalar(
                    select(Destination).where(Destination.iata_code == effective_dest_iata)
                )

    if orig == effective_dest_iata:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Les aéroports de départ et d'arrivée doivent être distincts.",
        )

    registry = get_provider_registry()
    raw_offers = await registry.flights.search_flights(
        origin_iata=orig,
        destination_iata=effective_dest_iata,
        departure_date=departure_date,
        return_date=return_date,
        travel_style=travel_style.upper(),
    )
    results: list[FlightOfferResponse] = []
    for offer in raw_offers:
        offer_dest_iata = str(offer.get("destination_iata", effective_dest_iata)).upper()
        if offer_dest_iata != effective_dest_iata:
            continue
        price_raw = offer.get("price_amount", offer.get("price_eur", "0.00"))
        price_dec = Decimal(str(price_raw)).quantize(Decimal("0.01"))
        city_label = (
            resolved_dest.city_name
            if resolved_dest is not None
            else str(offer.get("destination_city", effective_dest_iata))
        )
        results.append(
            FlightOfferResponse(
                offer_id=offer["offer_id"],
                airline_code=offer["airline_code"],
                airline_name=offer["airline_name"],
                flight_number_outbound=offer["flight_number_outbound"],
                flight_number_inbound=offer["flight_number_inbound"],
                origin_iata=orig,
                destination_iata=effective_dest_iata,
                destination_city=city_label,
                departure_outbound_at=offer["departure_outbound_at"],
                arrival_outbound_at=offer["arrival_outbound_at"],
                departure_inbound_at=offer["departure_inbound_at"],
                arrival_inbound_at=offer["arrival_inbound_at"],
                cabin_class=offer["cabin_class"],
                price_amount=price_dec,
                price_eur=float(price_dec),
                currency=offer.get("currency", "EUR"),
                mode=offer.get("mode", registry.flights.mode),
            )
        )
    return results


@router.post("/book", response_model=FlightBookingResponse, status_code=status.HTTP_201_CREATED)
async def book_flight_atomically(
    payload: FlightBookingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlightBookingResponse:
    """
    Réservation de billet d'avion atomique, idempotente et cohérente :
    1. Vérifie l'idempotence (idempotency_key ou même vol sur le séjour).
    2. Transaction DB atomique :
       - Chiffre le billet dans VaultDocument (AES-256-GCM) ;
       - Ajoute la dépense (Decimal + devise) dans BudgetItem ;
       - Met à jour Trip.arrival_at et Trip.departure_at (en UTC) ;
       - Crée FlightBooking et exécute db.commit().
       Si le coffre-fort ou la base échoue, toute la transaction est annulée (rollback).
    3. APRÈS le commit : envoie l'e-mail de confirmation via l'adaptateur Gmail
       avec nouvelle tentative automatique en cas d'échec, sans jamais annuler la réservation.
    """
    trip = await db.scalar(
        select(Trip).where(Trip.id == payload.trip_id, Trip.owner_id == current_user.id)
    )
    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voyage introuvable ou accès non autorisé.",
        )

    trip_dest = await db.scalar(
        select(Destination).where(Destination.id == trip.destination_id)
    )
    effective_origin_iata = payload.origin_iata.upper()
    if trip_dest and trip_dest.iata_code:
        expected_dest_iata = trip_dest.iata_code.upper()
        if payload.destination_iata.upper() != expected_dest_iata:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"La destination envoyée ({payload.destination_iata.upper()}) ne correspond pas "
                    f"à la destination du séjour ({trip_dest.city_name} - {expected_dest_iata})."
                ),
            )
        effective_dest_iata = expected_dest_iata
    else:
        effective_dest_iata = payload.destination_iata.upper()

    dep_out_utc = _ensure_utc(payload.departure_outbound_at)
    arr_out_utc = _ensure_utc(payload.arrival_outbound_at)
    dep_in_utc = _ensure_utc(payload.departure_inbound_at)
    arr_in_utc = _ensure_utc(payload.arrival_inbound_at)

    # 1. Vérification d'idempotence
    existing_by_key = await db.scalar(
        select(FlightBooking).where(FlightBooking.idempotency_key == payload.idempotency_key)
    )
    if existing_by_key:
        if existing_by_key.trip_id != trip.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cette clé d'idempotence est déjà associée à un autre voyage.",
            )
        return _to_booking_response(
            existing_by_key,
            trip,
            idempotent_replay=True,
            steps={
                "booking_created": True,
                "trip_dates_updated": True,
                "vault_encrypted": True,
                "budget_expense_added": True,
                "gmail_sent": existing_by_key.gmail_confirmation_sent,
            },
        )

    existing_same_flight = await db.scalar(
        select(FlightBooking).where(
            FlightBooking.trip_id == trip.id,
            FlightBooking.flight_number_outbound == payload.flight_number_outbound,
            FlightBooking.flight_number_inbound == payload.flight_number_inbound,
            FlightBooking.departure_outbound_at == dep_out_utc,
        )
    )
    if existing_same_flight:
        return _to_booking_response(
            existing_same_flight,
            trip,
            idempotent_replay=True,
            steps={
                "booking_created": True,
                "trip_dates_updated": True,
                "vault_encrypted": True,
                "budget_expense_added": True,
                "gmail_sent": existing_same_flight.gmail_confirmation_sent,
            },
        )

    steps = {
        "vault_encrypted": False,
        "budget_expense_added": False,
        "trip_dates_updated": False,
        "booking_created": False,
        "gmail_sent": False,
    }
    current_step = "initialization"
    pnr = f"TM{uuid.uuid4().hex[:6].upper()}"
    passenger = payload.passenger_name or current_user.full_name
    recipient = payload.recipient_email or current_user.email
    price_dec = payload.price_amount.quantize(Decimal("0.01"))

    try:
        # Étape A : Chiffrement du billet électronique dans le coffre-fort (AES-256-GCM)
        current_step = "vault_encrypted"
        cipher = get_envelope_cipher()
        eticket_payload = json.dumps(
            {
                "document": "E-TICKET_RECEIPT",
                "pnr": pnr,
                "passenger": passenger,
                "airline": payload.airline,
                "outbound": {
                    "flight": payload.flight_number_outbound,
                    "origin": effective_origin_iata,
                    "destination": effective_dest_iata,
                    "departure_at": dep_out_utc.isoformat(),
                    "arrival_at": arr_out_utc.isoformat(),
                },
                "inbound": {
                    "flight": payload.flight_number_inbound,
                    "origin": effective_dest_iata,
                    "destination": effective_origin_iata,
                    "departure_at": dep_in_utc.isoformat(),
                    "arrival_at": arr_in_utc.isoformat(),
                },
                "price_amount": str(price_dec),
                "currency": payload.currency,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        encrypted = cipher.encrypt_document(eticket_payload)
        vault_doc = VaultDocument(
            trip_id=trip.id,
            owner_id=current_user.id,
            doc_type=DocumentType.FLIGHT_TICKET.value,
            title=f"Billet d'avion {effective_origin_iata} <-> {effective_dest_iata} ({pnr})",
            mime_type="application/json",
            is_shared=False,
            encrypted_payload=encrypted["encrypted_payload"],  # type: ignore[arg-type]
            encryption_iv=encrypted["encryption_iv"],  # type: ignore[arg-type]
            encrypted_dek=encrypted["encrypted_dek"],  # type: ignore[arg-type]
            checksum_sha256=str(encrypted["checksum_sha256"]),
        )
        db.add(vault_doc)
        await db.flush()
        steps["vault_encrypted"] = True

        # Étape B : Enregistrement de la dépense en Decimal avec devise dans BudgetItem
        current_step = "budget_expense_added"
        budget_item = BudgetItem(
            trip_id=trip.id,
            category=BudgetCategory.FLIGHT.value,
            title=f"Vol A/R {payload.airline} ({payload.flight_number_outbound}/{payload.flight_number_inbound}) - PNR {pnr}",
            planned_amount=price_dec,
            actual_amount=price_dec,
            currency=payload.currency,
        )
        db.add(budget_item)
        await db.flush()
        steps["budget_expense_added"] = True

        # Étape C : Mise à jour de la fenêtre stricte du séjour sur Trip (stockage UTC)
        current_step = "trip_dates_updated"
        trip.arrival_at = arr_out_utc
        trip.departure_at = dep_in_utc
        trip.status = TripStatus.BOOKED.value
        steps["trip_dates_updated"] = True

        # Étape D : Création de l'enregistrement FlightBooking et COMMIT de la transaction
        current_step = "booking_created"
        booking = FlightBooking(
            trip_id=trip.id,
            idempotency_key=payload.idempotency_key,
            pnr_reference=pnr,
            airline=payload.airline,
            flight_number_outbound=payload.flight_number_outbound,
            flight_number_inbound=payload.flight_number_inbound,
            origin_iata=effective_origin_iata,
            destination_iata=effective_dest_iata,
            departure_outbound_at=dep_out_utc,
            arrival_outbound_at=arr_out_utc,
            departure_inbound_at=dep_in_utc,
            arrival_inbound_at=arr_in_utc,
            price=price_dec,
            currency=payload.currency,
            cabin_class=payload.cabin_class,
            flight_status=FlightStatus.SCHEDULED.value,
            vault_document_id=vault_doc.id,
            budget_item_id=budget_item.id,
            gmail_confirmation_sent=False,
            gmail_send_status="PENDING",
            gmail_send_attempts=0,
        )
        db.add(booking)
        await db.commit()
        await db.refresh(booking)
        await db.refresh(trip)
        steps["booking_created"] = True

    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": f"Échec atomique lors de l'étape '{current_step}'. Transaction intégralement annulée (rollback).",
                "error": str(exc),
                "failed_step": current_step,
                "steps_completed_before_rollback": steps,
                "rolled_back": True,
            },
        ) from exc

    # Étape E (Post-Commit) : Envoi de la confirmation Gmail avec nouvelle tentative en cas d'échec
    email_sent = await _dispatch_confirmation_email_post_commit(
        db=db,
        booking=booking,
        recipient_email=recipient,
        passenger_name=passenger,
        max_attempts=2,
    )
    steps["gmail_sent"] = email_sent

    return _to_booking_response(booking, trip, idempotent_replay=False, steps=steps)


@router.post("/{booking_id}/retry-email", response_model=FlightBookingResponse)
async def retry_flight_booking_email(
    booking_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlightBookingResponse:
    """Relance l'envoi de l'email de confirmation après une panne temporaire de Gmail."""
    booking = await db.scalar(select(FlightBooking).where(FlightBooking.id == booking_id))
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Réservation de vol introuvable.",
        )
    trip = await db.scalar(
        select(Trip).where(Trip.id == booking.trip_id, Trip.owner_id == current_user.id)
    )
    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voyage associé introuvable ou accès refusé.",
        )

    email_sent = await _dispatch_confirmation_email_post_commit(
        db=db,
        booking=booking,
        recipient_email=current_user.email,
        passenger_name=current_user.full_name,
        max_attempts=1,
    )
    return _to_booking_response(
        booking,
        trip,
        idempotent_replay=False,
        steps={
            "booking_created": True,
            "trip_dates_updated": True,
            "vault_encrypted": bool(booking.vault_document_id),
            "budget_expense_added": bool(booking.budget_item_id),
            "gmail_sent": email_sent,
        },
    )


@router.get("/trip/{trip_id}", response_model=list[FlightBookingResponse])
async def list_trip_flight_bookings(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FlightBookingResponse]:
    trip = await db.scalar(select(Trip).where(Trip.id == trip_id, Trip.owner_id == current_user.id))
    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voyage introuvable.",
        )
    stmt = (
        select(FlightBooking)
        .where(FlightBooking.trip_id == trip.id)
        .order_by(FlightBooking.departure_outbound_at.asc())
    )
    bookings = list((await db.scalars(stmt)).all())
    return [
        _to_booking_response(
            b,
            trip,
            idempotent_replay=False,
            steps={
                "booking_created": True,
                "trip_dates_updated": True,
                "vault_encrypted": bool(b.vault_document_id),
                "budget_expense_added": bool(b.budget_item_id),
                "gmail_sent": b.gmail_confirmation_sent,
            },
        )
        for b in bookings
    ]
