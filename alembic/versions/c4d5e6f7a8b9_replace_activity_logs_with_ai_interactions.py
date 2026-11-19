"""replace activity_logs with ai_interaction_logs

Revision ID: c4d5e6f7a8b9
Revises: f97f7d9317af
Create Date: 2026-10-01 00:00:00.000000

Reemplaza la tabla activity_logs (actividad de documentos) por
ai_interaction_logs (historial de interacciones con la IA).

MIGRACIÓN DESTRUCTIVA: se eliminan los datos de activity_logs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'f97f7d9317af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Eliminar tabla antigua (destructivo)
    op.drop_table('activity_logs')

    # 2. Crear nueva tabla ai_interaction_logs
    op.create_table(
        'ai_interaction_logs',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('question', mysql.LONGTEXT(), nullable=False),
        sa.Column('answer', mysql.LONGTEXT(), nullable=True),
        sa.Column('channel', sa.Enum('text', 'voice', name='ai_channel_enum'), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('status', sa.Enum('success', 'error', 'no_context', name='ai_interaction_status_enum'), nullable=False),
        sa.Column('error_message', mysql.LONGTEXT(), nullable=True),
        sa.Column('sources', mysql.LONGTEXT(), nullable=True),
        sa.Column('sources_info', mysql.LONGTEXT(), nullable=True),
        sa.Column('processing_time_ms', sa.Integer(), nullable=True),
        sa.Column('from_cache', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('conversation_id', sa.Integer(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_id'], ['Curim_conversations.id'], ondelete='SET NULL'),
    )

    # 3. Índices
    op.create_index('ix_ai_interaction_logs_id', 'ai_interaction_logs', ['id'])
    op.create_index('ix_ai_interaction_logs_user_id', 'ai_interaction_logs', ['user_id'])
    op.create_index('ix_ai_interaction_logs_channel', 'ai_interaction_logs', ['channel'])
    op.create_index('ix_ai_interaction_logs_status', 'ai_interaction_logs', ['status'])
    op.create_index('ix_ai_interaction_logs_timestamp', 'ai_interaction_logs', ['timestamp'])
    op.create_index('ix_ai_interaction_logs_conversation_id', 'ai_interaction_logs', ['conversation_id'])
    op.create_index('idx_ai_user_timestamp', 'ai_interaction_logs', ['user_id', 'timestamp'])
    op.create_index('idx_ai_channel_status', 'ai_interaction_logs', ['channel', 'status'])


def downgrade() -> None:
    # Revertir: eliminar ai_interaction_logs y recrear activity_logs
    op.drop_table('ai_interaction_logs')

    op.create_table(
        'activity_logs',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('document_name', sa.String(length=255), nullable=True),
        sa.Column('document_type', sa.Enum('pdf', 'docx', 'txt', name='activity_file_type_enum'), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )
    op.create_index('ix_activity_logs_id', 'activity_logs', ['id'])
    op.create_index('ix_activity_logs_timestamp', 'activity_logs', ['timestamp'])