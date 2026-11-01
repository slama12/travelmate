from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, ConfigDict, Field, field_validator


CATEGORY_INPUT_MAP: dict[str, str] = {
    "FLIGHT": "FLIGHT",
    "VOL": "FLIGHT",
    "VOLS": "FLIGHT",
    "ACCOMMODATION": "ACCOMMODATION",
    "HEBERGEMENT": "ACCOMMODATION",
    "HÉBERGEMENT": "ACCOMMODATION",
    "HOTEL": "ACCOMMODATION",
    "HÔTEL": "ACCOMMODATION",
    "ACTIVITY": "ACTIVITY",
    "ACTIVITIES": "ACTIVITY",
    "ACTIVITE": "ACTIVITY",
    "ACTIVITÉ": "ACTIVITY",
    "ACTIVITES": "ACTIVITY",
    "ACTIVITÉS": "ACTIVITY",
    "VISITE": "ACTIVITY",
    "MEAL": "MEAL",
    "FOOD": "MEAL",
    "REPAS": "MEAL",
    "RESTAURANT": "MEAL",
    "NOURRITURE": "MEAL",
    "TRANSPORT": "TRANSPORT",
    "TRANSPORTS": "TRANSPORT",
    "TRAJET": "TRANSPORT",
    "OTHER": "OTHER",
    "AUTRE": "OTHER",
}

CATEGORY_LABELS_FR: dict[str, str] = {
    "FLIGHT": "Vol",
    "ACCOMMODATION": "Hébergement",
    "ACTIVITY": "Activités",
    "MEAL": "Repas",
    "TRANSPORT": "Transports",
    "OTHER": "Autre",
}

# Taux de change déterministes en Decimal pour 1 EUR
EXCHANGE_RATES_PER_EUR: dict[str, Decimal] = {
    "EUR": Decimal("1.00"),
    "USD": Decimal("1.08"),
    "GBP": Decimal("0.85"),
    "CHF": Decimal("0.94"),
    "CAD": Decimal("1.48"),
    "MAD": Decimal("10.80"),
    "JPY": Decimal("162.00"),
    "THB": Decimal("38.50"),
    "SGD": Decimal("1.45"),
    "AUD": Decimal("1.65"),
    "BRL": Decimal("5.40"),
    "MXN": Decimal("18.50"),
    "AED": Decimal("3.97"),
    "TRY": Decimal("35.00"),
    "KRW": Decimal("1450.00"),
}


def quantize_money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_budget_category(raw_cat: str) -> str:
    key = (raw_cat or "").strip().upper()
    if key in CATEGORY_INPUT_MAP:
        return CATEGORY_INPUT_MAP[key]
    raise ValueError(
        f"Catégorie de dépense invalide : {raw_cat!r}. "
        "Valeurs autorisées : FLIGHT, ACCOMMODATION, ACTIVITY, MEAL, TRANSPORT."
    )


def convert_currency_decimal(
    amount: Decimal | str | int | float,
    from_currency: str,
    to_currency: str = "EUR",
) -> tuple[Decimal, Decimal]:
    """
    Convertit `amount` de `from_currency` vers `to_currency` uniquement en `Decimal`.
    Retourne `(converted_amount, applied_rate)`.
    """
    dec_amount = quantize_money(amount)
    src = (from_currency or "EUR").strip().upper()
    dst = (to_currency or "EUR").strip().upper()
    if src not in EXCHANGE_RATES_PER_EUR:
        raise ValueError(f"Devise source non prise en charge : {src}")
    if dst not in EXCHANGE_RATES_PER_EUR:
        raise ValueError(f"Devise cible non prise en charge : {dst}")
    if src == dst:
        return dec_amount, Decimal("1.0000")

    src_per_eur = EXCHANGE_RATES_PER_EUR[src]
    dst_per_eur = EXCHANGE_RATES_PER_EUR[dst]
    amount_in_eur = dec_amount / src_per_eur
    converted = (amount_in_eur * dst_per_eur).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rate = (dst_per_eur / src_per_eur).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return converted, rate


class BudgetExpenseCreateRequest(BaseModel):
    """Formulaire d'ajout de dépense manuelle (avec rattachement optionnel à une étape)."""

    amount: Decimal = Field(..., gt=Decimal("0.00"))
    category: str = Field(..., min_length=2, max_length=40)
    title: str = Field(..., min_length=2, max_length=255)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    stage_id: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _validate_amount(cls, v: Decimal | str | int | float) -> Decimal:
        return quantize_money(v)

    @field_validator("category")
    @classmethod
    def _validate_cat(cls, v: str) -> str:
        return normalize_budget_category(v)

    @field_validator("currency")
    @classmethod
    def _validate_curr(cls, v: str) -> str:
        curr = (v or "EUR").strip().upper()
        if curr not in EXCHANGE_RATES_PER_EUR:
            raise ValueError(
                f"Devise non supportée : {curr}. Devises acceptées : {', '.join(sorted(EXCHANGE_RATES_PER_EUR))}."
            )
        return curr


class BudgetPlannedUpdateRequest(BaseModel):
    """Mise à jour du budget total prévu (1 champ)."""

    total_budget_planned: Decimal = Field(..., gt=Decimal("0.00"))

    @field_validator("total_budget_planned", mode="before")
    @classmethod
    def _validate_planned(cls, v: Decimal | str | int | float) -> Decimal:
        return quantize_money(v)


class CurrencyConvertResponse(BaseModel):
    original_amount: Decimal
    from_currency: str
    to_currency: str
    converted_amount: Decimal
    exchange_rate: Decimal
    formatted_fr: str


class BudgetCategoryBreakdownSchema(BaseModel):
    category: str
    label_fr: str
    spent_amount: Decimal
    share_percent: Decimal
    items_count: int


class BudgetExpenseItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    stage_id: str | None = None
    stage_order_index: int | None = None
    stage_city_name: str | None = None
    category: str
    category_label_fr: str
    title: str
    amount: Decimal
    currency: str
    original_amount: Decimal
    original_currency: str
    exchange_rate: Decimal
    is_committed: bool
    source_label_fr: str
    created_at_fr: str


class BudgetStageBreakdownSchema(BaseModel):
    stage_id: str
    order_index: int
    city_name: str
    country_name: str
    country: str = ""
    nights: int
    planned_amount: Decimal | None = None
    spent_amount: Decimal
    total_spent: Decimal = Decimal("0.00")
    share_percent: Decimal
    items_count: int
    categories: list[BudgetCategoryBreakdownSchema] = Field(default_factory=list)
    items: list[BudgetExpenseItemResponse] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        if not self.country and self.country_name:
            self.country = self.country_name
        if self.total_spent == Decimal("0.00") and self.spent_amount != Decimal("0.00"):
            self.total_spent = self.spent_amount


class TripBudgetSummaryResponse(BaseModel):
    trip_id: str
    destination_city: str
    currency: str
    total_planned: Decimal
    total_spent: Decimal
    remaining: Decimal
    excess_amount: Decimal
    usage_percent: Decimal
    over_budget_alert: bool
    alert_level: str
    alert_message_fr: str | None = None
    categories: list[BudgetCategoryBreakdownSchema]
    stages_breakdown: list[BudgetStageBreakdownSchema] = Field(default_factory=list)
    items: list[BudgetExpenseItemResponse]
    supported_currencies: list[str]
    exchange_rates_per_eur: dict[str, Decimal]
