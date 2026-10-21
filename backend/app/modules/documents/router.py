import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select

from app.core.database import AsyncSession, get_db
from app.core.rbac import READ_ROLES, WRITE_ROLES, require_trip_access
from app.core.security import get_envelope_cipher
from app.models.entities import Destination, Trip, User, VaultDocument
from app.modules.auth.router import get_current_user
from app.modules.documents.schemas import (
    DOC_TYPE_LABELS_FR,
    DocumentCreateRequest,
    DocumentDecryptedResponse,
    DocumentShareUpdateRequest,
    DocumentSummaryResponse,
    TripDocumentsListResponse,
    normalize_doc_type,
)

router = APIRouter()

MONTHS_FR = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}


def format_date_fr(d: date | datetime | None) -> str:
    if d is None:
        now = datetime.now(timezone.utc)
        return f"{now.day} {MONTHS_FR[now.month]} {now.year}"
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day} {MONTHS_FR.get(d.month, 'novembre')} {d.year}"


def _resolve_doc_owner_id(doc: VaultDocument, trip: Trip) -> str:
    return str(doc.owner_id or trip.owner_id)


def _can_user_view_document(doc: VaultDocument, trip: Trip, user_id: str) -> bool:
    """
    Règle stricte Étape 5A :
    Documents visibles uniquement par leur propriétaire sauf partage explicite (`is_shared=True`).
    """
    owner_id = _resolve_doc_owner_id(doc, trip)
    return owner_id == user_id or bool(doc.is_shared)


def _evaluate_expiration(doc: VaultDocument, trip: Trip) -> tuple[bool, str | None]:
    if doc.expires_on is None:
        return False, None
    exp_date = doc.expires_on
    exp_fr = format_date_fr(exp_date)
    ref_end_date = (
        trip.departure_at.date()
        if isinstance(trip.departure_at, datetime)
        else date(2026, 11, 15)
    )
    if (doc.doc_type or "").upper() == "PASSPORT":
        if exp_date <= ref_end_date:
            return (
                True,
                f"Attention : votre passeport expire le {exp_fr}, avant la fin du voyage. Renouvelez-le avant le départ.",
            )
        if exp_date <= ref_end_date + timedelta(days=180):
            return (
                True,
                f"Rappel : votre passeport expire le {exp_fr} (moins de 6 mois après votre retour). Vérifiez la durée de validité demandée à l'entrée du pays.",
            )
    elif exp_date < ref_end_date:
        return (
            True,
            f"Attention : ce document expire le {exp_fr}, avant la fin de votre séjour.",
        )
    return False, None


def _serialize_doc_summary(
    doc: VaultDocument,
    trip: Trip,
    current_user_id: str,
) -> DocumentSummaryResponse:
    owner_id = _resolve_doc_owner_id(doc, trip)
    dtype = (doc.doc_type or "OTHER").upper()
    warn, warn_msg = _evaluate_expiration(doc, trip)
    # Nettoyage des libellés pour éviter tout jargon technique ("PNR") dans l'interface
    clean_title = (doc.title or "Document de voyage").replace("PNR ", "Réf. ").replace("(PNR", "(Réf.")
    return DocumentSummaryResponse(
        id=doc.id,
        trip_id=doc.trip_id,
        owner_id=owner_id,
        is_owner=(owner_id == current_user_id),
        is_shared=bool(doc.is_shared),
        doc_type=dtype,
        doc_type_label_fr=DOC_TYPE_LABELS_FR.get(dtype, "Autre document"),
        title=clean_title,
        mime_type=doc.mime_type or "text/plain",
        checksum_sha256=doc.checksum_sha256,
        encrypted_at_rest=True,
        expires_on_fr=format_date_fr(doc.expires_on) if doc.expires_on else None,
        expiration_warning=warn,
        expiration_message_fr=warn_msg,
        created_at_fr=format_date_fr(doc.created_at),
    )


def _format_decrypted_bytes(raw_bytes: bytes, mime_type: str) -> str:
    text = raw_bytes.decode("utf-8", errors="replace")
    if mime_type == "application/json":
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "airline" in data and "outbound" in data:
                out = data.get("outbound") or {}
                inb = data.get("inbound") or {}
                ref = data.get("pnr_reference") or ""
                return (
                    f"Compagnie : {data.get('airline')} — Référence : {ref}\n"
                    f"Passager : {data.get('passenger_name', 'Voyageur')}\n"
                    f"Aller : Vol {out.get('flight_number', '')} ({out.get('origin', '')} → {out.get('destination', '')})\n"
                    f"Retour : Vol {inb.get('flight_number', '')} ({inb.get('origin', '')} → {inb.get('destination', '')})\n"
                    f"Montant réglé : {data.get('price_amount', '')} {data.get('currency', 'EUR')}"
                )
        except Exception:
            pass
    return text


async def build_trip_documents_list(
    db: AsyncSession,
    trip: Trip,
    destination: Destination,
    current_user_id: str,
    role: str,
) -> TripDocumentsListResponse:
    rows = (
        await db.scalars(
            select(VaultDocument)
            .where(VaultDocument.trip_id == trip.id)
            .order_by(VaultDocument.created_at.desc())
        )
    ).all()

    visible_docs: list[DocumentSummaryResponse] = []
    passport_alert = False
    passport_msg: str | None = None

    for row in rows:
        if not _can_user_view_document(row, trip, current_user_id):
            continue
        summary = _serialize_doc_summary(row, trip, current_user_id)
        if summary.doc_type == "PASSPORT" and summary.expiration_warning and not passport_alert:
            passport_alert = True
            passport_msg = summary.expiration_message_fr
        visible_docs.append(summary)

    return TripDocumentsListResponse(
        trip_id=trip.id,
        destination_city=destination.city_name,
        current_user_role=role,
        passport_expiration_alert=passport_alert,
        passport_alert_message_fr=passport_msg,
        documents=visible_docs,
    )


@router.get("/trip/{trip_id}", response_model=TripDocumentsListResponse)
async def list_trip_documents(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripDocumentsListResponse:
    """
    Liste les documents du voyage accessibles à l'utilisateur connecté :
    seuls ses propres documents et les documents explicitement partagés (`is_shared=True`) sont retournés.
    """
    trip, destination, role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=READ_ROLES
    )
    return await build_trip_documents_list(db, trip, destination, current_user.id, role)


@router.post(
    "/trip/{trip_id}",
    response_model=DocumentDecryptedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_trip_document(
    trip_id: str,
    payload: DocumentCreateRequest,
    is_shared: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDecryptedResponse:
    """
    Ajoute un document chiffré côté serveur (AES-256-GCM enveloppe).
    4 champs de formulaire : titre, catégorie, contenu, date d'expiration optionnelle.
    Visible uniquement par son propriétaire par défaut (`is_shared=False`).
    """
    trip, _destination, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    cipher = get_envelope_cipher()
    plaintext_bytes = payload.content_text.strip().encode("utf-8")
    encrypted = cipher.encrypt_document(plaintext_bytes)

    doc = VaultDocument(
        trip_id=trip.id,
        owner_id=current_user.id,
        doc_type=normalize_doc_type(payload.doc_type),
        title=payload.title.strip(),
        mime_type="text/plain",
        is_shared=bool(is_shared),
        expires_on=payload.expires_on,
        encrypted_payload=encrypted["encrypted_payload"],  # type: ignore[arg-type]
        encryption_iv=encrypted["encryption_iv"],  # type: ignore[arg-type]
        encrypted_dek=encrypted["encrypted_dek"],  # type: ignore[arg-type]
        checksum_sha256=str(encrypted["checksum_sha256"]),
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    summary = _serialize_doc_summary(doc, trip, current_user.id)
    clean_text = payload.content_text.strip()
    return DocumentDecryptedResponse(
        **summary.model_dump(),
        decrypted_content=clean_text,
        content_text=clean_text,
    )


@router.get("/trip/{trip_id}/{doc_id}", response_model=DocumentDecryptedResponse)
async def get_decrypted_trip_document(
    trip_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDecryptedResponse:
    """
    Déchiffre et retourne le contenu d'un document côté serveur :
    - Refuse avec 403 si l'utilisateur n'est pas membre du voyage ;
    - Refuse avec 403 si le document appartient à un autre utilisateur et n'est pas explicitement partagé (`is_shared=False`).
    """
    trip, _destination, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=READ_ROLES
    )
    doc = await db.scalar(
        select(VaultDocument).where(
            VaultDocument.id == doc_id,
            VaultDocument.trip_id == trip.id,
        )
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable.",
        )
    if not _can_user_view_document(doc, trip, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé : ce document est privé et visible uniquement par son propriétaire.",
        )

    cipher = get_envelope_cipher()
    raw_bytes = cipher.decrypt_document(
        doc.encrypted_payload,
        doc.encryption_iv,
        doc.encrypted_dek,
    )
    summary = _serialize_doc_summary(doc, trip, current_user.id)
    dec_text = _format_decrypted_bytes(raw_bytes, doc.mime_type or "text/plain")
    return DocumentDecryptedResponse(
        **summary.model_dump(),
        decrypted_content=dec_text,
        content_text=dec_text,
    )


@router.patch("/trip/{trip_id}/{doc_id}/share", response_model=DocumentSummaryResponse)
async def update_trip_document_sharing(
    trip_id: str,
    doc_id: str,
    payload: DocumentShareUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentSummaryResponse:
    """
    Active ou désactive le partage explicite d'un document avec les autres membres du voyage.
    Seul le propriétaire du document (ou le propriétaire du voyage) peut modifier son partage.
    """
    trip, _destination, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    doc = await db.scalar(
        select(VaultDocument).where(
            VaultDocument.id == doc_id,
            VaultDocument.trip_id == trip.id,
        )
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable.",
        )
    doc_owner_id = _resolve_doc_owner_id(doc, trip)
    if current_user.id != doc_owner_id and current_user.id != trip.owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé : seul le propriétaire du document peut gérer son partage.",
        )

    doc.is_shared = bool(payload.is_shared)
    await db.commit()
    await db.refresh(doc)
    return _serialize_doc_summary(doc, trip, current_user.id)


@router.delete("/trip/{trip_id}/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trip_document(
    trip_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Supprime un document du voyage.
    Seul le propriétaire du document (ou le propriétaire du voyage) ayant les droits d'écriture peut le supprimer.
    """
    trip, _destination, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    doc = await db.scalar(
        select(VaultDocument).where(
            VaultDocument.id == doc_id,
            VaultDocument.trip_id == trip.id,
        )
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable.",
        )
    doc_owner_id = _resolve_doc_owner_id(doc, trip)
    if current_user.id != doc_owner_id and current_user.id != trip.owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé : seul le propriétaire du document peut le supprimer.",
        )

    await db.delete(doc)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
