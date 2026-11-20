"""
Router para autenticación de dos factores (2FA).

Flujo:
  1. POST /auth/2fa/setup    → secreto pendiente + QR (aún no activa nada).
  2. POST /auth/2fa/confirm  → verifica el primer código, activa el 2FA y
                               devuelve los códigos de respaldo (una sola vez).
  3. POST /auth/2fa/regenerate-backup-codes → códigos nuevos; exige código TOTP.
  4. POST /auth/2fa/disable  → con código de la app o de respaldo.

El estado (activado o no) viene en el perfil del usuario (`two_factor_enabled`).
Los endpoints que verifican códigos tienen límite de intentos para impedir
adivinar un código de 6 dígitos por fuerza bruta.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limit
from app.db.database import get_db
from app.models.models import User
from app.schemas.auth_schemas import (
    BackupCodesResponse,
    TwoFactorConfirmRequest,
    TwoFactorConfirmResponse,
    TwoFactorDisableRequest,
    TwoFactorSetupResponse,
)
from app.services.auth_service import TwoFactorAuthService, get_current_user

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger(__name__)

INVALID_CODE = "Código inválido o ya usado"


@router.post(
    "/2fa/setup",
    response_model=TwoFactorSetupResponse,
    dependencies=[Depends(rate_limit(10, 60))],
)
def setup_2fa(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Genera un secreto TOTP pendiente y su código QR. Se activa con /2fa/confirm."""
    if current_user.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA ya está habilitado. Desactívalo primero si quieres reconfigurarlo.",
        )
    try:
        secret, qr_code = TwoFactorAuthService.enable_2fa_for_user(current_user, db)
    except Exception:
        logger.exception(f"Error al iniciar 2FA para el usuario {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al configurar 2FA",
        )

    logger.info(f"2FA: configuración iniciada para el usuario {current_user.id}")
    return TwoFactorSetupResponse(
        secret=secret,
        qr_code=f"data:image/png;base64,{qr_code}",
        message="Escanea el código QR con tu aplicación de autenticación y verifica con un código",
    )


@router.post(
    "/2fa/confirm",
    response_model=TwoFactorConfirmResponse,
    dependencies=[Depends(rate_limit(5, 60))],
)
def confirm_2fa_setup(
    data: TwoFactorConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activa el 2FA con el primer código y devuelve los códigos de respaldo."""
    try:
        backup_codes = TwoFactorAuthService.confirm_2fa_setup(current_user, data.code, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if backup_codes is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_CODE)

    logger.info(f"2FA: activado para el usuario {current_user.id}")
    return TwoFactorConfirmResponse(
        message="2FA habilitado exitosamente",
        enabled=True,
        enabled_at=current_user.two_factor_enabled_at or datetime.now(timezone.utc),
        backup_codes=backup_codes,
    )


@router.post(
    "/2fa/disable",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(5, 60))],
)
def disable_2fa(
    data: TwoFactorDisableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Desactiva el 2FA con un código de la aplicación o un código de respaldo."""
    try:
        success = TwoFactorAuthService.disable_2fa_for_user(current_user, data.code, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_CODE)

    logger.info(f"2FA: desactivado para el usuario {current_user.id}")
    return {
        "message": "2FA deshabilitado exitosamente",
        "enabled": False,
        "disabled_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post(
    "/2fa/regenerate-backup-codes",
    response_model=BackupCodesResponse,
    dependencies=[Depends(rate_limit(5, 60))],
)
def regenerate_backup_codes(
    data: TwoFactorConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sustituye los códigos de respaldo. Exige un código válido de la aplicación."""
    if not current_user.two_factor_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA no está habilitado")

    backup_codes = TwoFactorAuthService.regenerate_backup_codes(current_user, data.code, db)
    if backup_codes is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_CODE)

    logger.info(f"2FA: códigos de respaldo regenerados para el usuario {current_user.id}")
    return BackupCodesResponse(
        backup_codes=backup_codes,
        message="Códigos de respaldo regenerados. Guárdalos en un lugar seguro.",
    )
