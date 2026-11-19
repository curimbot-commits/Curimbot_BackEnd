"""add content_hash to documents

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-10-02 00:00:00.000000

Añade content_hash a documents para detectar duplicados por usuario.
El hash se calcula sobre el texto extraído normalizado.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('content_hash', sa.String(length=64), nullable=True),
    )
    op.create_index(
        'idx_documents_uploaded_by_content_hash',
        'documents',
        ['uploaded_by', 'content_hash'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'idx_documents_uploaded_by_content_hash',
        table_name='documents',
    )
    op.drop_column('documents', 'content_hash')