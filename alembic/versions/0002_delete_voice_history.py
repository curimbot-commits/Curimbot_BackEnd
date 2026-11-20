"""delete voice history

El historial de interacciones pasa a ser solo de texto: la voz ya no se
registra (se quitó POST /api/v1/voice/log-interaction). Esta migración de
datos borra las filas de voz que quedaron guardadas. Borrado aprobado por
el usuario el 2026-11-20.

No es reversible: downgrade() no puede recuperar las filas borradas.

Revision ID: 0002_delete_voice_history
Revises: 0001_baseline
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002_delete_voice_history'
down_revision: Union[str, Sequence[str], None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM ai_interaction_logs WHERE channel = 'voice'")


def downgrade() -> None:
    # Las filas borradas no se pueden recuperar; no hay nada que deshacer.
    pass
