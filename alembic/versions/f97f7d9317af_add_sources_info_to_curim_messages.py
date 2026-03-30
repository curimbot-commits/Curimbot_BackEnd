"""add sources_info to curim_messages

Revision ID: f97f7d9317af
Revises: b9a43276b145
Create Date: 2026-03-29 19:52:21.916614

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f97f7d9317af'
down_revision: Union[str, Sequence[str], None] = 'b9a43276b145'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Añadir la columna sources_info de forma segura
    # Usamos curim_messages (minúsculas) que es como existe en la DB actualmente
    op.add_column('curim_messages', sa.Column('sources_info', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('curim_messages', 'sources_info')
