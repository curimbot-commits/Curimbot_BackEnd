from enum import Enum

class UserRole(str, Enum):
    admin = "admin"
    user = "user"

class LogAction(str, Enum):
    upload = "upload"
    download = "download"
    delete = "delete"
    search = "search"
    login = "login"
    ENABLE_2FA = "enable_2fa"

class FileType(str, Enum):
    pdf = "pdf"
    docx = "docx"
    txt = "txt"

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