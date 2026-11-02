"""Voyage multi-villes étape 1 : table trip_stages et rattachement des séjours existants

Revision ID: 0009_multi_city_stages_step1
Revises: 0008_place_photos_step3
Create Date: 2026-11-01 16:10:00.000000
"""

from datetime import date, datetime, timedelta, timezone
import json
from typing import Sequence, Union
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alembic import op
import sqlalchemy as sa

# Identifiant court (<= 32 caractères pour VARCHAR(32) de alembic_version)
revision: str = "0009_multi_city_stages_step1"
down_revision: Union[str, Sequence[str], None] = "0008_place_photos_step3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHILD_TABLES_WITH_STAGE_ID: tuple[str, ...] = (
    "flight_bookings",
    "accommodation_bookings",
    "itinerary_items",
    "budget_items",
)


def _parse_dt(val: object) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        raw = val.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _resolve_tz(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo((tz_name or "UTC").strip() or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "trip_stages" not in existing_tables:
        op.create_table(
            "trip_stages",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "trip_id",
                sa.String(length=36),
                sa.ForeignKey("trips.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("order_index", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "destination_id",
                sa.String(length=36),
                sa.ForeignKey("destinations.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("geoname_id", sa.Integer(), nullable=True),
            sa.Column("city_name", sa.String(length=120), nullable=False),
            sa.Column("country_name", sa.String(length=120), nullable=False),
            sa.Column("country_code_iso2", sa.String(length=2), nullable=False, server_default="XX"),
            sa.Column("arrival_date", sa.Date(), nullable=False),
            sa.Column("nights", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("departure_date", sa.Date(), nullable=False),
            sa.Column("arrival_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("departure_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
            sa.Column(
                "arrival_transport_mode",
                sa.String(length=32),
                nullable=False,
                server_default="VOL",
            ),
            sa.Column("departure_transport_mode", sa.String(length=32), nullable=True),
            sa.Column("transport_unlocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("transport_booking_ref", sa.String(length=80), nullable=True),
            sa.Column("selected_place_ids", sa.JSON(), nullable=False),
            sa.Column("planned_budget", sa.Numeric(12, 2), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_trip_stages_trip_id", "trip_stages", ["trip_id"], unique=False)
        op.create_index("ix_trip_stages_destination_id", "trip_stages", ["destination_id"], unique=False)
        op.create_index("ix_trip_stages_geoname_id", "trip_stages", ["geoname_id"], unique=False)
        op.create_index("ix_trip_stages_arrival_date", "trip_stages", ["arrival_date"], unique=False)
        op.create_index("ix_trip_stages_departure_date", "trip_stages", ["departure_date"], unique=False)
        op.create_index(
            "ix_trip_stages_trip_order",
            "trip_stages",
            ["trip_id", "order_index"],
            unique=False,
        )

    is_sqlite = bind.dialect.name == "sqlite"
    for table_name in CHILD_TABLES_WITH_STAGE_ID:
        if table_name not in existing_tables:
            continue
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        if "stage_id" not in existing_cols:
            if is_sqlite:
                with op.batch_alter_table(table_name) as batch_op:
                    batch_op.add_column(sa.Column("stage_id", sa.String(length=36), nullable=True))
                    batch_op.create_index(f"ix_{table_name}_stage_id", ["stage_id"], unique=False)
                    batch_op.create_foreign_key(
                        f"fk_{table_name}_stage_id",
                        "trip_stages",
                        ["stage_id"],
                        ["id"],
                        ondelete="SET NULL",
                    )
            else:
                op.add_column(table_name, sa.Column("stage_id", sa.String(length=36), nullable=True))
                op.create_index(f"ix_{table_name}_stage_id", table_name, ["stage_id"], unique=False)
                op.create_foreign_key(
                    f"fk_{table_name}_stage_id",
                    table_name,
                    "trip_stages",
                    ["stage_id"],
                    ["id"],
                    ondelete="SET NULL",
                )

    # Rattachement automatique de chaque séjour existant à un voyage d'une seule étape
    if "trips" in existing_tables and "destinations" in existing_tables:
        destinations_rows = bind.execute(
            sa.text(
                "SELECT id, geoname_id, city_name, country_name, country_code_iso2, timezone "
                "FROM destinations"
            )
        ).mappings().all()
        dest_by_id = {str(r["id"]): dict(r) for r in destinations_rows}

        existing_stage_trip_ids = {
            str(r[0])
            for r in bind.execute(sa.text("SELECT DISTINCT trip_id FROM trip_stages")).fetchall()
        }

        bookings_by_trip: dict[str, str] = {}
        if "flight_bookings" in existing_tables:
            for b_row in bind.execute(
                sa.text("SELECT trip_id, pnr_reference FROM flight_bookings")
            ).mappings().all():
                bookings_by_trip[str(b_row["trip_id"])] = str(b_row["pnr_reference"] or "")

        trips_rows = bind.execute(
            sa.text(
                "SELECT id, destination_id, arrival_at, departure_at, "
                "selected_place_ids, total_budget_planned, created_at "
                "FROM trips"
            )
        ).mappings().all()

        now_utc = datetime.now(timezone.utc)
        trip_stages_table = sa.table(
            "trip_stages",
            sa.column("id", sa.String),
            sa.column("trip_id", sa.String),
            sa.column("order_index", sa.Integer),
            sa.column("destination_id", sa.String),
            sa.column("geoname_id", sa.Integer),
            sa.column("city_name", sa.String),
            sa.column("country_name", sa.String),
            sa.column("country_code_iso2", sa.String),
            sa.column("arrival_date", sa.Date),
            sa.column("nights", sa.Integer),
            sa.column("departure_date", sa.Date),
            sa.column("arrival_at", sa.DateTime(timezone=True)),
            sa.column("departure_at", sa.DateTime(timezone=True)),
            sa.column("timezone", sa.String),
            sa.column("arrival_transport_mode", sa.String),
            sa.column("departure_transport_mode", sa.String),
            sa.column("transport_unlocked", sa.Boolean),
            sa.column("transport_booking_ref", sa.String),
            sa.column("selected_place_ids", sa.JSON),
            sa.column("planned_budget", sa.Numeric),
            sa.column("created_at", sa.DateTime(timezone=True)),
        )

        for t_row in trips_rows:
            trip_id = str(t_row["id"])
            if trip_id in existing_stage_trip_ids:
                continue

            dest_id = str(t_row["destination_id"])
            dest = dest_by_id.get(dest_id, {})
            tz_name = str(dest.get("timezone") or "UTC")
            tz = _resolve_tz(tz_name)

            arr_utc = _parse_dt(t_row["arrival_at"]) or datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
            dep_utc = _parse_dt(t_row["departure_at"]) or (arr_utc + timedelta(days=3))
            if dep_utc <= arr_utc:
                dep_utc = arr_utc + timedelta(days=1)

            arr_local_date: date = arr_utc.astimezone(tz).date()
            dep_local_date: date = dep_utc.astimezone(tz).date()
            nights = max(1, (dep_local_date - arr_local_date).days)
            dep_local_date = arr_local_date + timedelta(days=nights)

            raw_selected = t_row["selected_place_ids"]
            if isinstance(raw_selected, str):
                try:
                    selected_places = json.loads(raw_selected)
                except Exception:
                    selected_places = []
            elif isinstance(raw_selected, list):
                selected_places = list(raw_selected)
            else:
                selected_places = []

            has_flight = trip_id in bookings_by_trip
            pnr_ref = bookings_by_trip.get(trip_id) or None
            created_utc = _parse_dt(t_row["created_at"]) or now_utc
            stage_id = str(uuid.uuid4())

            bind.execute(
                trip_stages_table.insert().values(
                    id=stage_id,
                    trip_id=trip_id,
                    order_index=1,
                    destination_id=dest_id,
                    geoname_id=dest.get("geoname_id"),
                    city_name=str(dest.get("city_name") or "Ville"),
                    country_name=str(dest.get("country_name") or "Monde"),
                    country_code_iso2=str(dest.get("country_code_iso2") or "XX")[:2],
                    arrival_date=arr_local_date,
                    nights=nights,
                    departure_date=dep_local_date,
                    arrival_at=arr_utc,
                    departure_at=dep_utc,
                    timezone=tz_name,
                    arrival_transport_mode="VOL",
                    departure_transport_mode="VOL",
                    transport_unlocked=has_flight,
                    transport_booking_ref=pnr_ref,
                    selected_place_ids=selected_places,
                    planned_budget=t_row["total_budget_planned"],
                    created_at=created_utc,
                )
            )

            for child_table in CHILD_TABLES_WITH_STAGE_ID:
                if child_table in existing_tables:
                    bind.execute(
                        sa.text(
                            f"UPDATE {child_table} SET stage_id = :stage_id "
                            f"WHERE trip_id = :trip_id AND stage_id IS NULL"
                        ),
                        {"stage_id": stage_id, "trip_id": trip_id},
                    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    is_sqlite = bind.dialect.name == "sqlite"

    for table_name in reversed(CHILD_TABLES_WITH_STAGE_ID):
        if table_name not in existing_tables:
            continue
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        if "stage_id" in existing_cols:
            if is_sqlite:
                with op.batch_alter_table(table_name) as batch_op:
                    batch_op.drop_constraint(f"fk_{table_name}_stage_id", type_="foreignkey")
                    batch_op.drop_index(f"ix_{table_name}_stage_id")
                    batch_op.drop_column("stage_id")
            else:
                op.drop_constraint(f"fk_{table_name}_stage_id", table_name, type_="foreignkey")
                op.drop_index(f"ix_{table_name}_stage_id", table_name=table_name)
                op.drop_column(table_name, "stage_id")

    if "trip_stages" in existing_tables:
        op.drop_index("ix_trip_stages_trip_order", table_name="trip_stages")
        op.drop_index("ix_trip_stages_departure_date", table_name="trip_stages")
        op.drop_index("ix_trip_stages_arrival_date", table_name="trip_stages")
        op.drop_index("ix_trip_stages_geoname_id", table_name="trip_stages")
        op.drop_index("ix_trip_stages_destination_id", table_name="trip_stages")
        op.drop_index("ix_trip_stages_trip_id", table_name="trip_stages")
        op.drop_table("trip_stages")
