from sqlalchemy import (
    Boolean, Column, Integer, String, Text, DateTime,
    ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone
from sqlalchemy import Enum as SqlEnum

from .base import Base
from app.enums.enums import LogAction, NotificationType, NotificationChannel, NotificationStatus

def utc_now():
    return datetime.now(timezone.utc)

class UserPreferences(Base):
    """Preferencias personalizadas del usuario."""
    __tablename__ = "user_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    email_notifications = Column(Boolean, default=True, nullable=False)
    push_notifications = Column(Boolean, default=False, nullable=False)
    weekly_summary = Column(Boolean, default=True, nullable=False)
    login_alerts = Column(Boolean, default=True, nullable=False)
    security_alerts = Column(Boolean, default=True, nullable=False)
    weekly_summary_format = Column(String(10), default="pdf", nullable=False)

    
    language = Column(String(5), default="es", nullable=False)
    theme = Column(String(10), default="light", nullable=False)
    
    profile_photo_url = Column(String(500), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    
    user = relationship("User", back_populates="preferences")
    
    def __repr__(self):
        return f"<UserPreferences(user_id={self.user_id}, lang={self.language}, theme={self.theme})>"


class Log(Base):
    """Logs del sistema para auditoría."""
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(SqlEnum(LogAction, name="log_action_enum"), nullable=False, index=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    user = relationship("User", back_populates="logs")

    def __repr__(self):
        return f"<Log(id={self.id}, user_id={self.user_id}, action={self.action})>"


class NotificationHistory(Base):
    """Registro histórico de notificaciones enviadas."""
    __tablename__ = "notification_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    type = Column(SqlEnum(NotificationType, name="notification_type_enum"), nullable=False, index=True)
    channel = Column(SqlEnum(NotificationChannel, name="notification_channel_enum"), nullable=False, index=True)
    status = Column(SqlEnum(NotificationStatus, name="notification_status_enum"), nullable=False, index=True)
    
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    user = relationship("User", back_populates="notifications")

    def __repr__(self):
        return f"<NotificationHistory(user_id={self.user_id}, type={self.type}, status={self.status})>"
