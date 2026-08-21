"""add match_results announcement message columns

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-22 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd4e5f6a7b8c9'
down_revision: str | None = 'c3d4e5f6a7b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'match_results', sa.Column('announce_channel_id', sa.BigInteger(), nullable=True)
    )
    op.add_column(
        'match_results', sa.Column('announce_message_id', sa.BigInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('match_results', 'announce_message_id')
    op.drop_column('match_results', 'announce_channel_id')
