"""add logs_url column to runs

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-05-15 13:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("logs_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "logs_url")
