"""add review message reference to applications

Revision ID: a1b2c3d4e5f6
Revises: 4ced0c4116e9
Create Date: 2026-08-15 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '4ced0c4116e9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'applications', sa.Column('review_channel_id', sa.BigInteger(), nullable=True)
    )
    op.add_column(
        'applications', sa.Column('review_message_id', sa.BigInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('applications', 'review_message_id')
    op.drop_column('applications', 'review_channel_id')
