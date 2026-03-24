"""Add is_public to documents

Revision ID: b9a43276b145
Revises: cf55924dda68
Create Date: 2026-03-23 22:48:31.828314

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'b9a43276b145'
down_revision: Union[str, Sequence[str], None] = 'cf55924dda68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('is_public', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('documents', 'is_public')
