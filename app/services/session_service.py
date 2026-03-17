import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException, status
from user_agents import parse  # pip install pycountry user-agents

from app.models.models import ActiveSession, User, BlacklistedToken
from app.services import security_service
from jose import jwt

logger = logging.getLogger(__name__)


class SessionService:
    """Servicio para gestionar sesiones activas de usuarios"""
    
    @staticmethod
    def extract_device_info(user_agent: str) -> dict:
        """
        Extrae información detallada del User-Agent
        
        Args:
            user_agent: String del User-Agent
            
        Returns:
            Dict con browser, os, device_type y display_name
        """
        try:
            ua = parse(user_agent)
            browser = f"{ua.browser.family} {ua.browser.version_string.split('.')[0]}"
            os = f"{ua.os.family} {ua.os.version_string}" if ua.os.version_string else ua.os.family
            
            device_type = "Desktop"
            if ua.is_mobile:
                device_type = "Mobile"
            elif ua.is_tablet:
                device_type = "Tablet"
            elif ua.is_bot:
                device_type = "Bot"
                
            display_name = f"{browser} on {os}"
            if device_type != "Desktop":
                display_name += f" ({device_type})"
                
            return {
                "browser": browser,
                "os": os,
                "device_type": device_type,
                "display_name": display_name
            }
        except Exception as e:
            logger.warning(f"Error parsing user agent: {e}")
            return {
                "browser": "Desconocido",
                "os": "Desconocido",
                "device_type": "Desktop",
                "display_name": "Dispositivo desconocido"
            }
    
    @staticmethod
    def get_location_from_ip(ip_address: str) -> str:
        """
        Obtiene ubicación aproximada desde IP usando API externa
        
        Args:
            ip_address: Dirección IP
            
        Returns:
            String con ubicación o "Ubicación desconocida"
        """
        # TODO: Implementar con API de geolocalización
        # Opciones: ipapi.co, ip-api.com, ipinfo.io
        
        # Por ahora retornar placeholder
        if ip_address in ["127.0.0.1", "localhost", "unknown"]:
            return "Conexión local"
        
        # Ejemplo con ip-api.com (requiere requests)
        try:
            import requests
            response = requests.get(f"http://ip-api.com/json/{ip_address}", timeout=2)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    city = data.get("city", "")
                    country = data.get("country", "")
                    return f"{city}, {country}" if city and country else country or "Ubicación desconocida"
        except Exception as e:
            logger.warning(f"Error getting location for IP {ip_address}: {e}")
        
        return "Ubicación desconocida"
    
    @staticmethod
    def extract_jti_from_token(token: str) -> Optional[str]:
        """
        Extrae el JTI (JWT ID) de un token sin validarlo completamente
        
        Args:
            token: Token JWT
            
        Returns:
            JTI o None si no se puede extraer
        """
        try:
            unverified_payload = jwt.get_unverified_claims(token)
            return unverified_payload.get("jti")
        except Exception as e:
            logger.warning(f"Error extracting JTI from token: {e}")
            return None
    
    @staticmethod
    def create_session(
        user_id: Optional[int],
        access_token: str,
        refresh_token: str,
        ip_address: str,
        user_agent: str,
        db: Session,
        is_current: bool = True
    ) -> ActiveSession:
        """
        Crea una nueva sesión activa en la base de datos
        
        Args:
            user_id: ID del usuario (opcional si se puede extraer del token)
            access_token: Token de acceso JWT
            refresh_token: Token de refresh JWT
            ip_address: IP del cliente
            user_agent: User-Agent del cliente
            db: Sesión de base de datos
            is_current: Si es la sesión actual del request
            
        Returns:
            ActiveSession creada
        """
        try:
            # Si no se provee user_id, intentar extraerlo del token de acceso
            if user_id is None:
                try:
                    payload = jwt.get_unverified_claims(access_token)
                    user_id = int(payload.get("sub"))
                except Exception as e:
                    logger.error(f"No se pudo extraer user_id del token: {e}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token inválido: user_id no encontrado"
                    )

            # Extraer JTIs de los tokens
            access_jti = SessionService.extract_jti_from_token(access_token)
            refresh_jti = SessionService.extract_jti_from_token(refresh_token)
            
            if not access_jti or not refresh_jti:
                logger.warning("No se pudo extraer JTI de los tokens")
                # Usar hash como fallback
                import hashlib
                access_jti = hashlib.sha256(access_token.encode()).hexdigest()[:50]
                refresh_jti = hashlib.sha256(refresh_token.encode()).hexdigest()[:50]
            
            # Decodificar refresh token para obtener expiración
            refresh_payload = jwt.get_unverified_claims(refresh_token)
            expires_timestamp = refresh_payload.get("exp")
            expires_at = datetime.fromtimestamp(expires_timestamp) if expires_timestamp else (
                datetime.now(timezone.utc) + timedelta(days=7)
            )
            
            # Extraer información del dispositivo
            ua_info = SessionService.extract_device_info(user_agent)
            device = ua_info["display_name"]
            location = SessionService.get_location_from_ip(ip_address)
            
            # Marcar otras sesiones como no actuales si esta es actual
            if is_current:
                db.query(ActiveSession).filter(
                    ActiveSession.user_id == user_id,
                    ActiveSession.is_current == True
                ).update({"is_current": False})
            
            # Crear nueva sesión
            session = ActiveSession(
                user_id=user_id,
                access_token_jti=access_jti,
                refresh_token_jti=refresh_jti,
                device=device,
                ip_address=ip_address,
                user_agent=user_agent,
                location=location,
                created_at=datetime.now(timezone.utc),
                last_active=datetime.now(timezone.utc),
                expires_at=expires_at,
                is_current=is_current,
                is_active=True
            )
            
            db.add(session)
            db.commit()
            db.refresh(session)
            
            return session
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Error creando sesión: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al crear sesión"
            )
    
    @staticmethod
    def get_user_sessions(user_id: int, db: Session, active_only: bool = True) -> List[ActiveSession]:
        """
        Obtiene todas las sesiones de un usuario
        
        Args:
            user_id: ID del usuario
            db: Sesión de base de datos
            active_only: Si solo retornar sesiones activas
            
        Returns:
            Lista de sesiones
        """
        try:
            query = db.query(ActiveSession).filter(ActiveSession.user_id == user_id)
            
            if active_only:
                query = query.filter(
                    ActiveSession.is_active == True,
                    ActiveSession.expires_at > datetime.now(timezone.utc)
                )
            
            sessions = query.order_by(ActiveSession.last_active.desc()).all()
            
            # Aumentar sesiones con info de dispositivo para el frontend
            for s in sessions:
                if s.user_agent:
                    info = SessionService.extract_device_info(s.user_agent)
                    s.browser = info["browser"]
                    s.os = info["os"]
                    s.device_type = info["device_type"]
                else:
                    s.browser = "Desconocido"
                    s.os = "Desconocido"
                    s.device_type = "Desktop"

            return sessions
            
        except SQLAlchemyError as e:
            logger.error(f"Error obteniendo sesiones del usuario {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al obtener sesiones"
            )
    
    @staticmethod
    def revoke_session(
        session_id: int,
        user_id: int,
        db: Session,
        requester_user_id: int
    ) -> dict:
        """
        Revoca una sesión específica
        
        Args:
            session_id: ID de la sesión a revocar
            user_id: ID del propietario de la sesión
            db: Sesión de base de datos
            requester_user_id: ID del usuario que solicita la revocación
            
        Returns:
            Diccionario con mensaje de éxito
        """
        try:
            # Verificar que el usuario pueda revocar esta sesión
            session = db.query(ActiveSession).filter(
                ActiveSession.id == session_id,
                ActiveSession.user_id == user_id
            ).first()
            
            if not session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Sesión no encontrada"
                )
            
            # Solo el propietario puede revocar sus sesiones
            if user_id != requester_user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tienes permisos para revocar esta sesión"
                )
            
            # Agregar tokens a blacklist
            blacklist_access = BlacklistedToken(
                token=session.access_token_jti,
                blacklisted_at=datetime.now(timezone.utc)
            )
            blacklist_refresh = BlacklistedToken(
                token=session.refresh_token_jti,
                blacklisted_at=datetime.now(timezone.utc)
            )
            
            db.add(blacklist_access)
            db.add(blacklist_refresh)
            
            # Eliminar sesión
            db.delete(session)
            db.commit()
                        
            return {
                "message": "Sesión revocada exitosamente",
                "session_id": session_id
            }
            
        except HTTPException:
            raise
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Error revocando sesión {session_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al revocar sesión"
            )
    
    @staticmethod
    def revoke_all_sessions(
        user_id: int,
        db: Session,
        except_current: bool = True,
        current_session_id: Optional[int] = None
    ) -> dict:
        """
        Revoca todas las sesiones de un usuario
        
        Args:
            user_id: ID del usuario
            db: Sesión de base de datos
            except_current: Si mantener la sesión actual activa
            current_session_id: ID de la sesión actual (si except_current=True)
            
        Returns:
            Diccionario con mensaje y conteo
        """
        try:
            query = db.query(ActiveSession).filter(ActiveSession.user_id == user_id)
            
            if except_current and current_session_id:
                query = query.filter(ActiveSession.id != current_session_id)
            
            sessions = query.all()
            count = len(sessions)
            
            # Agregar tokens a blacklist
            for session in sessions:
                db.add(BlacklistedToken(token=session.access_token_jti, blacklisted_at=datetime.now(timezone.utc)))
                db.add(BlacklistedToken(token=session.refresh_token_jti, blacklisted_at=datetime.now(timezone.utc)))
                db.delete(session)
            
            db.commit()
                        
            return {
                "message": f"{count} sesiones revocadas exitosamente",
                "count": count
            }
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Error revocando sesiones del usuario {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al revocar sesiones"
            )
    
    @staticmethod
    def update_session_activity(access_token_jti: str, db: Session) -> None:
        """
        Actualiza el timestamp de última actividad de una sesión
        
        Args:
            access_token_jti: JTI del token de acceso
            db: Sesión de base de datos
        """
        try:
            db.query(ActiveSession).filter(
                ActiveSession.access_token_jti == access_token_jti
            ).update({"last_active": datetime.now(timezone.utc)})
            
            db.commit()
            
        except SQLAlchemyError as e:
            logger.warning(f"Error actualizando actividad de sesión: {e}")
            # No lanzar excepción, no es crítico
    
    @staticmethod
    def cleanup_expired_sessions(db: Session) -> int:
        """
        Limpia sesiones expiradas de la base de datos
        
        Args:
            db: Sesión de base de datos
            
        Returns:
            Número de sesiones eliminadas
        """
        try:
            expired = db.query(ActiveSession).filter(
                ActiveSession.expires_at < datetime.now(timezone.utc)
            )
            
            count = expired.count()
            expired.delete()
            db.commit()
            
            return count
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Error limpiando sesiones expiradas: {e}")
            return 0