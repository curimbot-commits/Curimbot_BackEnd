"""two factor hardening

- Amplía two_factor_secret y two_factor_secret_temp a 255 caracteres: el
  secreto TOTP pasa a guardarse cifrado con Fernet (unos 140 caracteres).
- Añade two_factor_last_timestep: último periodo TOTP aceptado, para que un
  código no se pueda reutilizar.
- Cifra los secretos que ya existían en texto plano. Si alguno quedara sin
  cifrar, la aplicación lo sigue leyendo (TwoFactorAuthService.decrypt_secret).

Revision ID: 0003_two_factor_hardening
Revises: 0002_delete_voice_history
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0003_two_factor_hardening'
down_revision: Union[str, Sequence[str], None] = '0002_delete_voice_history'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FERNET_PREFIX = "gAAAA"
SECRET_COLUMNS = ("two_factor_secret", "two_factor_secret_temp")

LOG_ACTIONS = (
    'login', 'logout', 'register', 'password_change', 'password_reset',
    'profile_update', 'document_upload', 'document_download', 'document_delete', 'error',
)
NEW_LOG_ACTIONS = ('two_factor_enabled', 'two_factor_disabled')


def _log_action_enum(values):
    return sa.Enum(*values, name='log_action_enum')


def upgrade() -> None:
    # Activar el 2FA fallaba con 500: el código registraba una acción de log
    # que no existía en el enum. Se añaden las acciones del 2FA.
    op.alter_column(
        "logs", "action",
        existing_type=_log_action_enum(LOG_ACTIONS),
        type_=_log_action_enum(LOG_ACTIONS + NEW_LOG_ACTIONS),
        existing_nullable=False,
    )

    for column in SECRET_COLUMNS:
        op.alter_column(
            "users", column,
            existing_type=sa.String(length=64), type_=sa.String(length=255),
            existing_nullable=True,
        )
    op.add_column("users", sa.Column("two_factor_last_timestep", sa.BigInteger(), nullable=True))

    from app.services.storage_service import encrypt_bytes

    conn = op.get_bind()
    for column in SECRET_COLUMNS:
        rows = conn.execute(
            sa.text(f"SELECT id, {column} FROM users WHERE {column} IS NOT NULL")
        ).fetchall()
        for user_id, value in rows:
            if value.startswith(FERNET_PREFIX):
                continue
            conn.execute(
                sa.text(f"UPDATE users SET {column} = :v WHERE id = :id"),
                {"v": encrypt_bytes(value.encode()).decode(), "id": user_id},
            )


def downgrade() -> None:
    from app.services.storage_service import decrypt_bytes

    conn = op.get_bind()
    for column in SECRET_COLUMNS:
        rows = conn.execute(
            sa.text(f"SELECT id, {column} FROM users WHERE {column} IS NOT NULL")
        ).fetchall()
        for user_id, value in rows:
            if value.startswith(FERNET_PREFIX):
                conn.execute(
                    sa.text(f"UPDATE users SET {column} = :v WHERE id = :id"),
                    {"v": decrypt_bytes(value.encode()).decode(), "id": user_id},
                )

    op.drop_column("users", "two_factor_last_timestep")
    for column in SECRET_COLUMNS:
        op.alter_column(
            "users", column,
            existing_type=sa.String(length=255), type_=sa.String(length=64),
            existing_nullable=True,
        )

    op.execute(
        "DELETE FROM logs WHERE action IN ('two_factor_enabled', 'two_factor_disabled')"
    )
    op.alter_column(
        "logs", "action",
        existing_type=_log_action_enum(LOG_ACTIONS + NEW_LOG_ACTIONS),
        type_=_log_action_enum(LOG_ACTIONS),
        existing_nullable=False,
    )
