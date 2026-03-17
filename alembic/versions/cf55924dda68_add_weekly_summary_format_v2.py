"""add weekly_summary_format_v2

Revision ID: cf55924dda68
Revises: dbf6f029038d
Create Date: 2026-03-16 20:24:18.116069

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf55924dda68'
down_revision: Union[str, Sequence[str], None] = 'dbf6f029038d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_preferences', sa.Column('weekly_summary_format', sa.String(length=10), nullable=False, server_default='pdf'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_preferences', 'weekly_summary_format')
