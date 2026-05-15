"""add provision_attempts to runs

Revision ID: a1b2c3d4e5f6
Revises: 17bbb767e50b
Create Date: 2026-05-15 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "17bbb767e50b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "provision_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "provision_attempts")
