"""
Módulo de modelos ORM para base de datos.
    
Este archivo sirve como punto central de exportación para todos los modelos del sistema.
Los modelos han sido separados por dominio para mejor mantenibilidad:
- base.py: Base declarativa y mixins
- auth_models.py: Manejo de usuarios, roles, sesiones y tokens
- document_models.py: Manejo de documentos y actividades
- preference_models.py: Preferencias y logs del sistema
- Curim_models.py: Entidades para el asistente de IA
"""

# Import and expose everything to maintain backwards compatibility 
from .base import Base, TimestampMixin
from .auth_models import (
    Role, User, LoginAttempt, LoginAlert, 
    ActiveSession, PasswordResetToken, BlacklistedToken
)
from .document_models import Document, ActivityLog
from .preference_models import UserPreferences, Log, NotificationHistory
from .Curim_models import CurimConversation, CurimMessage, CurimDocumentIndex

__all__ = [
    "Base", "TimestampMixin",
    "Role", "User", "LoginAttempt", "LoginAlert", 
    "ActiveSession", "PasswordResetToken", "BlacklistedToken",
    "Document", "ActivityLog",
    "UserPreferences", "Log", "NotificationHistory",
    "CurimConversation", "CurimMessage", "CurimDocumentIndex"
]