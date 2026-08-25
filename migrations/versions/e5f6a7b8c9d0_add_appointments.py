"""add appointments (staff-appointed players for teamless games)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-24 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e5f6a7b8c9d0'
down_revision: str | None = 'd4e5f6a7b8c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'appointments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('appointed_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'],
                                name='fk_appointments_event_id_events'),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'],
                                name='fk_appointments_game_id_games'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'],
                                name='fk_appointments_user_id_users'),
        sa.ForeignKeyConstraint(['appointed_by'], ['users.id'],
                                name='fk_appointments_appointed_by_users'),
        sa.PrimaryKeyConstraint('id', name='pk_appointments'),
        sa.UniqueConstraint('event_id', 'game_id', 'user_id', name='appointment_unique'),
    )


def downgrade() -> None:
    op.drop_table('appointments')
