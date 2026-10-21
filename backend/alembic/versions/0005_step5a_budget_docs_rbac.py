"""Step 5A budget, vault document ownership/sharing/expiration, and RBAC

Revision ID: 0005_step5a_budget_docs_rbac
Revises: 0004_weather_ai_chat
Create Date: 2026-10-20 13:45:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_step5a_budget_docs_rbac"
down_revision: str | None = "0004_weather_ai_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vault_documents",
        sa.Column("owner_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "vault_documents",
        sa.Column(
            "is_shared",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "vault_documents",
        sa.Column("expires_on", sa.Date(), nullable=True),
    )
    op.create_index(
        "ix_vault_documents_owner_id",
        "vault_documents",
        ["owner_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_vault_documents_owner_id_users",
        "vault_documents",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_vault_documents_owner_id_users",
        "vault_documents",
        type_="foreignkey",
    )
    op.drop_index("ix_vault_documents_owner_id", table_name="vault_documents")
    op.drop_column("vault_documents", "expires_on")
    op.drop_column("vault_documents", "is_shared")
    op.drop_column("vault_documents", "owner_id")
