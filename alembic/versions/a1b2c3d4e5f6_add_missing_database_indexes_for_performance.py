"""Final structural cleanup and missed indexes

Revision ID: a1b2c3d4e5f6
Revises: def858bcc56d
Create Date: 2026-03-15 10:10:00.000000

This migration adds MISSING indexes to MySQL. 
(Structural changes to blacklisted_tokens were applied in partial runs).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'def858bcc56d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Note: blacklisted_tokens columns (jti, expires_at) already added manually 
    # and 'token' dropped in previous partial run.

    # ── Missing Performance Indexes ─────────────────────────
    
    # blacklisted_tokens
    op.create_index('ix_blacklisted_tokens_jti', 'blacklisted_tokens', ['jti'], unique=True)
    op.create_index('ix_blacklisted_tokens_expires_at', 'blacklisted_tokens', ['expires_at'])

    # documents
    op.create_index('ix_documents_status', 'documents', ['status'])

    # activity_logs
    op.create_index('ix_activity_logs_timestamp', 'activity_logs', ['timestamp'])

    # logs
    op.create_index('ix_logs_created_at', 'logs', ['created_at'])


def downgrade() -> None:
    # Remove added indexes
    op.drop_index('ix_logs_created_at', table_name='logs')
    op.drop_index('ix_activity_logs_timestamp', table_name='activity_logs')
    op.drop_index('ix_documents_status', table_name='documents')
    op.drop_index('ix_blacklisted_tokens_expires_at', table_name='blacklisted_tokens')
    op.drop_index('ix_blacklisted_tokens_jti', table_name='blacklisted_tokens')
