"""
Router para autenticación de dos factores (2FA).

Implementa configuración TOTP, verificación, deshabilitación y gestión de
códigos de respaldo. Compatible con Google Authenticator, Microsoft Authenticator y Authy.
"""

import logging
from datetime import datetime, timezone
from .....schemas.auth_schemas import (
    BackupCodesResponse, TwoFactorConfirmRequest, TwoFactorDisableRequest,
    TwoFactorSetupResponse, TwoFactorVerifyRequest
)
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models.models import User
from app.services.auth_service import TwoFactorAuthService, get_current_user


# ========================================
# CONFIGURACIÓN
# ========================================

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger(__name__)


# ========================================
# ENDPOINTS DE AUTENTICACIÓN 2FA
# ========================================

@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
def setup_2fa(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Inicia la configuración de 2FA: genera secreto TOTP, código QR y 10 códigos de respaldo.
    El usuario debe completar la configuración llamando a `/2fa/confirm`.

    Raises:
        HTTPException 400: 2FA ya está habilitado.
        HTTPException 500: Error al generar secreto o QR.
    """
    try:
        if current_user.two_factor_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="2FA ya está habilitado. Desactívalo primero si quieres reconfigurarlo."
            )

        secret, qr_code = TwoFactorAuthService.enable_2fa_for_user(current_user, db)
        backup_codes = TwoFactorAuthService.generate_backup_codes()
        TwoFactorAuthService.save_backup_codes(current_user, backup_codes, db)

        logger.info(f"2FA setup initiated for user: {current_user.email}")

        return TwoFactorSetupResponse(
            secret=secret,
            qr_code=f"data:image/png;base64,{qr_code}",
            backup_codes=backup_codes,
            message="Escanea el código QR con Google Authenticator y verifica con un código"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error setting up 2FA for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al configurar 2FA"
        )


@router.post("/2fa/confirm", status_code=status.HTTP_200_OK)
def confirm_2fa_setup(
    data: TwoFactorConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Confirma la configuración de 2FA verificando un código TOTP.
    Tras la confirmación, todos los logins requerirán código 2FA.

    Raises:
        HTTPException 400: Código inválido o expirado.
        HTTPException 500: Error al confirmar 2FA.
    """
    try:
        success = TwoFactorAuthService.confirm_2fa_setup(current_user, data.code, db)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Código inválido o expirado"
            )

        logger.info(f"2FA confirmed and enabled for user: {current_user.email}")

        return {
            "message": "2FA habilitado exitosamente",
            "enabled": True,
            "enabled_at": datetime.now(timezone.utc).isoformat()
        }

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception(f"Error confirming 2FA for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al confirmar 2FA"
        )


@router.post("/2fa/disable", status_code=status.HTTP_200_OK)
def disable_2fa(
    data: TwoFactorDisableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Deshabilita 2FA requiriendo un código TOTP válido o código de respaldo.

    Raises:
        HTTPException 400: 2FA no habilitado o código inválido.
        HTTPException 500: Error al deshabilitar 2FA.
    """
    try:
        success = False
        try:
            success = TwoFactorAuthService.disable_2fa_for_user(current_user, data.code, db)
        except ValueError:
            success = TwoFactorAuthService.verify_backup_code(current_user, data.code, db)
            if success:
                current_user.two_factor_enabled = False
                current_user.two_factor_secret = None
                current_user.two_factor_disabled_at = datetime.now(timezone.utc)
                db.commit()

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Código inválido"
            )

        logger.info(f"2FA disabled for user: {current_user.email}")

        return {
            "message": "2FA deshabilitado exitosamente",
            "enabled": False,
            "disabled_at": datetime.now(timezone.utc).isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error disabling 2FA for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al deshabilitar 2FA"
        )


@router.get("/2fa/status", response_model=dict)
def get_2fa_status(
    current_user: User = Depends(get_current_user)
):
    """
    Retorna el estado actual de 2FA del usuario: si está habilitado,
    cuándo fue activado y si hay códigos de respaldo disponibles.
    """
    return {
        "enabled": current_user.two_factor_enabled,
        "enabled_at": current_user.two_factor_enabled_at.isoformat() if current_user.two_factor_enabled_at else None,
        "has_backup_codes": bool(current_user.backup_codes)
    }


@router.post("/2fa/backup-codes", response_model=BackupCodesResponse)
def get_backup_codes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Genera un nuevo conjunto de códigos de respaldo (los anteriores se invalidan).
    Requiere que 2FA esté habilitado.

    Raises:
        HTTPException 400: 2FA no está habilitado.
    """
    if not current_user.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA no está habilitado"
        )

    backup_codes = TwoFactorAuthService.generate_backup_codes()
    TwoFactorAuthService.save_backup_codes(current_user, backup_codes, db)

    logger.info(f"Backup codes generated via /backup-codes for user: {current_user.email}")

    return BackupCodesResponse(
        backup_codes=backup_codes,
        message="Códigos de respaldo generados. Guárdalos en un lugar seguro."
    )


@router.post("/2fa/regenerate-backup-codes", response_model=BackupCodesResponse)
def regenerate_backup_codes(
    code: str = Body(..., embed=True, description="Código 2FA para autorizar"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Regenera códigos de respaldo invalidando los anteriores.
    Requiere un código TOTP válido para autorizar la operación.

    Raises:
        HTTPException 400: 2FA no habilitado o código TOTP inválido.
        HTTPException 500: Error al regenerar códigos.
    """
    try:
        if not current_user.two_factor_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="2FA no está habilitado"
            )

        if not TwoFactorAuthService.verify_totp_code(current_user.two_factor_secret, code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Código inválido"
            )

        backup_codes = TwoFactorAuthService.generate_backup_codes()
        TwoFactorAuthService.save_backup_codes(current_user, backup_codes, db)

        logger.info(f"Backup codes regenerated for user: {current_user.email}")

        return BackupCodesResponse(
            backup_codes=backup_codes,
            message="Códigos de respaldo regenerados. Guárdalos en un lugar seguro."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error regenerating backup codes for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al regenerar códigos de respaldo"
        )
