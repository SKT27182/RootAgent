"""Infra admin hierarchy: link to main_db, rename GLOBAL_ADMIN

Revision ID: 002
Revises: 001
Create Date: 2026-05-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE userrole RENAME VALUE 'GLOBAL_ADMIN' TO 'INFRA_ADMIN'")
    op.add_column(
        "users",
        sa.Column("infra_hub_user_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_users_infra_hub_user_id"),
        "users",
        ["infra_hub_user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_infra_hub_user_id"), table_name="users")
    op.drop_column("users", "infra_hub_user_id")
    op.execute("ALTER TYPE userrole RENAME VALUE 'INFRA_ADMIN' TO 'GLOBAL_ADMIN'")
