import csv
import io
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select

from app.core.database import AsyncSession, get_db
from app.core.rbac import READ_ROLES, WRITE_ROLES, require_trip_access
from app.models.entities import BudgetItem, Destination, Trip, User
from app.modules.auth.router import get_current_user
from app.modules.budget.schemas import (
    CATEGORY_LABELS_FR,
    EXCHANGE_RATES_PER_EUR,
    BudgetCategoryBreakdownSchema,
    BudgetExpenseCreateRequest,
    BudgetExpenseItemResponse,
    BudgetPlannedUpdateRequest,
    CurrencyConvertResponse,
    TripBudgetSummaryResponse,
    convert_currency_decimal,
    normalize_budget_category,
    quantize_money,
)

router = APIRouter()

MAIN_BUDGET_CATEGORIES: list[str] = [
    "FLIGHT",
    "ACCOMMODATION",
    "ACTIVITY",
    "MEAL",
    "TRANSPORT",
]

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


def format_datetime_fr(dt: datetime | None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    return f"{dt.day} {MONTHS_FR.get(dt.month, 'novembre')} {dt.year}"


def _parse_item_currency_note(item: BudgetItem, trip_currency: str) -> tuple[Decimal, str, Decimal, str]:
    """
    Extrait la devise d'origine, le montant d'origine et le taux de change éventuel
    stockés lors d'une conversion, tout en restant 100% en Decimal.
    """
    amt = quantize_money(item.amount or Decimal("0.00"))
    curr = (item.currency or trip_currency or "EUR").upper()
    raw_title = item.title or ""
    # Format interne optionnel : "Libellé [ORIG:108.00:USD:0.9259]"
    if "[ORIG:" in raw_title and raw_title.endswith("]"):
        prefix, meta = raw_title.rsplit("[ORIG:", 1)
        clean_title = prefix.strip()
        parts = meta[:-1].split(":")
        if len(parts) >= 3:
            try:
                orig_amt = quantize_money(parts[0])
                orig_curr = parts[1].strip().upper()
                rate = Decimal(parts[2]).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                return orig_amt, orig_curr, rate, clean_title
            except Exception:
                pass
    return amt, curr, Decimal("1.0000"), raw_title


async def build_trip_budget_summary(
    db: AsyncSession,
    trip: Trip,
    destination: Destination,
) -> TripBudgetSummaryResponse:
    trip_currency = (trip.currency or "EUR").upper()
    total_planned = quantize_money(trip.total_budget_planned or Decimal("0.00"))

    rows = (
        await db.scalars(
            select(BudgetItem)
            .where(BudgetItem.trip_id == trip.id)
            .order_by(BudgetItem.created_at.desc())
        )
    ).all()

    cat_totals: dict[str, Decimal] = {cat: Decimal("0.00") for cat in MAIN_BUDGET_CATEGORIES}
    cat_counts: dict[str, int] = {cat: 0 for cat in MAIN_BUDGET_CATEGORIES}
    total_spent = Decimal("0.00")
    serialized_items: list[BudgetExpenseItemResponse] = []

    for row in rows:
        cat_key = (row.category or "OTHER").upper()
        if cat_key not in cat_totals:
            cat_key = "ACTIVITY" if cat_key == "OTHER" else cat_key
        amt = quantize_money(row.amount or Decimal("0.00"))
        if row.currency and row.currency.upper() != trip_currency:
            amt, _ = convert_currency_decimal(amt, row.currency.upper(), trip_currency)

        total_spent = quantize_money(total_spent + amt)
        if cat_key in cat_totals:
            cat_totals[cat_key] = quantize_money(cat_totals[cat_key] + amt)
            cat_counts[cat_key] += 1

        orig_amt, orig_curr, rate, clean_title = _parse_item_currency_note(row, trip_currency)
        cat_label_fr = CATEGORY_LABELS_FR.get(cat_key, "Autre")
        source_label = "Réservation enregistrée" if cat_key == "FLIGHT" and "Vol " in clean_title else "Dépense manuelle"

        serialized_items.append(
            BudgetExpenseItemResponse(
                id=row.id,
                trip_id=row.trip_id,
                category=cat_key,
                category_label_fr=cat_label_fr,
                title=clean_title,
                amount=amt,
                currency=trip_currency,
                original_amount=orig_amt,
                original_currency=orig_curr,
                exchange_rate=rate,
                is_committed=bool(row.is_committed),
                source_label_fr=source_label,
                created_at_fr=format_datetime_fr(row.created_at),
            )
        )

    if total_planned > Decimal("0.00"):
        usage_percent = ((total_spent * Decimal("100.00")) / total_planned).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        usage_percent = Decimal("0.00")

    if total_spent > total_planned:
        remaining = Decimal("0.00")
        excess_amount = quantize_money(total_spent - total_planned)
        over_budget_alert = True
        alert_level = "OVER_BUDGET"
        alert_message_fr = (
            f"Alerte dépassement : votre budget prévu de {total_planned} {trip_currency} "
            f"est dépassé de {excess_amount} {trip_currency} ({usage_percent} % utilisé)."
        )
    else:
        remaining = quantize_money(total_planned - total_spent)
        excess_amount = Decimal("0.00")
        over_budget_alert = False
        if usage_percent >= Decimal("85.00") and total_planned > Decimal("0.00"):
            alert_level = "NEAR_LIMIT"
            alert_message_fr = (
                f"Attention : vous avez utilisé {usage_percent} % de votre budget prévu "
                f"(reste {remaining} {trip_currency})."
            )
        else:
            alert_level = "OK"
            alert_message_fr = None

    categories_breakdown: list[BudgetCategoryBreakdownSchema] = []
    for cat in MAIN_BUDGET_CATEGORIES:
        c_spent = cat_totals[cat]
        if total_spent > Decimal("0.00"):
            share = ((c_spent * Decimal("100.00")) / total_spent).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            share = Decimal("0.00")
        categories_breakdown.append(
            BudgetCategoryBreakdownSchema(
                category=cat,
                label_fr=CATEGORY_LABELS_FR[cat],
                spent_amount=c_spent,
                share_percent=share,
                items_count=cat_counts[cat],
            )
        )

    return TripBudgetSummaryResponse(
        trip_id=trip.id,
        destination_city=destination.city_name,
        currency=trip_currency,
        total_planned=total_planned,
        total_spent=total_spent,
        remaining=remaining,
        excess_amount=excess_amount,
        usage_percent=usage_percent,
        over_budget_alert=over_budget_alert,
        alert_level=alert_level,
        alert_message_fr=alert_message_fr,
        categories=categories_breakdown,
        items=serialized_items,
        supported_currencies=sorted(EXCHANGE_RATES_PER_EUR.keys()),
        exchange_rates_per_eur=EXCHANGE_RATES_PER_EUR,
    )


@router.get("/convert", response_model=CurrencyConvertResponse)
async def convert_currency_endpoint(
    amount: Decimal = Query(..., gt=Decimal("0.00")),
    from_currency: str = Query(default="USD", min_length=3, max_length=3),
    to_currency: str = Query(default="EUR", min_length=3, max_length=3),
    current_user: User = Depends(get_current_user),
) -> CurrencyConvertResponse:
    """Convertit un montant d'une devise vers une autre en Decimal."""
    _ = current_user
    try:
        orig = quantize_money(amount)
        converted, rate = convert_currency_decimal(orig, from_currency, to_currency)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    src = from_currency.strip().upper()
    dst = to_currency.strip().upper()
    return CurrencyConvertResponse(
        original_amount=orig,
        from_currency=src,
        to_currency=dst,
        converted_amount=converted,
        exchange_rate=rate,
        formatted_fr=f"{orig} {src} = {converted} {dst} (taux {rate})",
    )


@router.get("/trip/{trip_id}", response_model=TripBudgetSummaryResponse)
async def get_trip_budget(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripBudgetSummaryResponse:
    """Retourne le résumé complet du budget du séjour (montants en Decimal)."""
    trip, destination, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=READ_ROLES
    )
    return await build_trip_budget_summary(db, trip, destination)


@router.patch("/trip/{trip_id}", response_model=TripBudgetSummaryResponse)
async def update_trip_planned_budget(
    trip_id: str,
    payload: BudgetPlannedUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripBudgetSummaryResponse:
    """Met à jour le budget total prévu du séjour (réservé au propriétaire et aux éditeurs)."""
    trip, destination, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    trip.total_budget_planned = quantize_money(payload.total_budget_planned)
    await db.commit()
    await db.refresh(trip)
    return await build_trip_budget_summary(db, trip, destination)


@router.post(
    "/trip/{trip_id}/items",
    response_model=TripBudgetSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/trip/{trip_id}/expenses",
    response_model=TripBudgetSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_manual_budget_expense(
    trip_id: str,
    payload: BudgetExpenseCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripBudgetSummaryResponse:
    """
    Ajoute une dépense manuelle (4 champs : montant, catégorie, libellé, devise).
    Convertit automatiquement le montant en Decimal vers la devise du voyage si nécessaire.
    """
    trip, destination, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    trip_currency = (trip.currency or "EUR").upper()
    orig_amount = quantize_money(payload.amount)
    orig_currency = payload.currency.upper()
    norm_category = normalize_budget_category(payload.category)

    converted_amount, rate = convert_currency_decimal(orig_amount, orig_currency, trip_currency)
    stored_title = payload.title.strip()
    if orig_currency != trip_currency:
        stored_title = f"{stored_title} [ORIG:{orig_amount}:{orig_currency}:{rate}]"

    item = BudgetItem(
        trip_id=trip.id,
        category=norm_category,
        title=stored_title,
        amount=converted_amount,
        currency=trip_currency,
        is_committed=True,
    )
    db.add(item)
    await db.commit()
    return await build_trip_budget_summary(db, trip, destination)


@router.delete("/trip/{trip_id}/items/{item_id}", response_model=TripBudgetSummaryResponse)
@router.delete("/trip/{trip_id}/expenses/{item_id}", response_model=TripBudgetSummaryResponse)
async def delete_budget_expense(
    trip_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripBudgetSummaryResponse:
    """Supprime une dépense du budget (réservé au propriétaire et aux éditeurs)."""
    trip, destination, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=WRITE_ROLES
    )
    item = await db.scalar(
        select(BudgetItem).where(
            BudgetItem.id == item_id,
            BudgetItem.trip_id == trip.id,
        )
    )
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dépense introuvable dans ce voyage.",
        )
    await db.delete(item)
    await db.commit()
    return await build_trip_budget_summary(db, trip, destination)


@router.get("/trip/{trip_id}/export.csv")
async def export_trip_budget_csv(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Exporte le récapitulatif et la liste des dépenses du séjour au format CSV (UTF-8)."""
    trip, destination, _role = await require_trip_access(
        db, trip_id, current_user.id, allowed_roles=READ_ROLES
    )
    summary = await build_trip_budget_summary(db, trip, destination)

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")
    writer.writerow(["Voyage", destination.city_name])
    writer.writerow(["Devise du voyage", summary.currency])
    writer.writerow(["Total prévu", f"{summary.total_planned:.2f}"])
    writer.writerow(["Total dépensé", f"{summary.total_spent:.2f}"])
    writer.writerow(["Solde restant", f"{summary.remaining:.2f}"])
    writer.writerow(["Dépassement", "Oui" if summary.over_budget_alert else "Non"])
    writer.writerow([])
    writer.writerow(["Répartition par catégorie", "Montant dépensé", "Part (%)", "Nombre de lignes"])
    for cat in summary.categories:
        writer.writerow([cat.label_fr, f"{cat.spent_amount:.2f}", f"{cat.share_percent:.2f}%", str(cat.items_count)])
    writer.writerow([])
    writer.writerow(
        [
            "Catégorie",
            "Libellé",
            f"Montant ({summary.currency})",
            "Devise d'origine",
            "Montant d'origine",
            "Date",
        ]
    )
    for it in summary.items:
        writer.writerow(
            [
                it.category_label_fr,
                it.title,
                f"{it.amount:.2f}",
                it.original_currency,
                f"{it.original_amount:.2f}",
                it.created_at_fr,
            ]
        )

    csv_bytes = buf.getvalue().encode("utf-8")
    filename = f"budget_{destination.city_name.lower().replace(' ', '_')}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
