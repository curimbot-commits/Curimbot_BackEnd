from enum import Enum


class UserRole(str, Enum):
    admin = "admin"
    user = "user"


class FileType(str, Enum):
    pdf = "pdf"
    docx = "docx"
    txt = "txt"


# =========================================================
# IA — Interacciones con Curim
# =========================================================

class AIChannel(str, Enum):
    """Canal por el cual el usuario interactúa con la IA."""
    text = "text"
    voice = "voice"


class AIInteractionStatus(str, Enum):
    """Estado de la respuesta de la IA."""
    success = "success"
    error = "error"
    no_context = "no_context"


# =========================================================
# Logs de sistema (auditoría interna)
# =========================================================

class LogAction(str, Enum):
    """
    Acciones registradas en el log de sistema (auditoría interna).

    NOTA: estos valores son un placeholder. Si tu modelo Log ya tiene
    datos con otros valores, ajústalos aquí para que coincidan.
    """
    login = "login"
    logout = "logout"
    register = "register"
    password_change = "password_change"
    password_reset = "password_reset"
    profile_update = "profile_update"
    document_upload = "document_upload"
    document_download = "document_download"
    document_delete = "document_delete"
    error = "error"
    two_factor_enabled = "two_factor_enabled"
    two_factor_disabled = "two_factor_disabled"


# =========================================================
# Notificaciones
# =========================================================

class NotificationType(str, Enum):
    LOGIN_ALERT = "login_alert"
    PASSWORD_CHANGED = "password_changed"
    WEEKLY_SUMMARY = "weekly_summary"
    SECURITY_ALERT = "security_alert"
    PROFILE_UPDATED = "profile_updated"
    PASSWORD_RESET = "password_reset"


class NotificationChannel(str, Enum):
    EMAIL = "email"
    PUSH = "push"
    IN_APP = "in_app"


class NotificationStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"