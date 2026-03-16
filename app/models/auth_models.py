from typing import Optional
from sqlalchemy import (
    Boolean, Column, Integer, String, Text, DateTime,
    ForeignKey, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone

from .base import Base, TimestampMixin

def utc_now():
    return datetime.now(timezone.utc)


class Role(Base):
    """Modelo de roles para control de acceso."""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)

    users = relationship("User", back_populates="role")

    def __repr__(self):
        return f"<Role(id={self.id}, name={self.name})>"


class User(Base, TimestampMixin):
    """Modelo de usuario principal."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    name = Column(String(100), nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False, index=True)
    role = relationship("Role", back_populates="users")
    
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    two_factor_enabled = Column(Boolean, default=False, nullable=False)
    two_factor_secret = Column(String(64), nullable=True)
    two_factor_secret_temp = Column(String(64), nullable=True)
    two_factor_enabled_at = Column(DateTime(timezone=True), nullable=True)
    two_factor_disabled_at = Column(DateTime(timezone=True), nullable=True)
    backup_codes = Column(Text, nullable=True)
    provider    = Column(String(50),  nullable=True)
    provider_id = Column(String(255), nullable=True, index=True)
    avatar      = Column(Text,        nullable=True)

    documents = relationship("Document", back_populates="owner", cascade="all, delete-orphan")
    logs = relationship("Log", back_populates="user")
    activities = relationship("ActivityLog", back_populates="user")
    preferences = relationship("UserPreferences", back_populates="user", uselist=False, cascade="all, delete-orphan")
    login_alerts = relationship("LoginAlert", back_populates="user", cascade="all, delete-orphan")
    active_sessions = relationship("ActiveSession", back_populates="user", cascade="all, delete-orphan")
    reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")
    Curim_conversations = relationship("CurimConversation", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role.name})>"

    @property
    def is_admin(self) -> bool:
        return self.role and self.role.name == "admin"
    
    @property
    def is_user(self) -> bool:
        return self.role and self.role.name == "user"


class LoginAttempt(Base):
    """Registro de intentos de login."""
    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), index=True, nullable=False)
    ip_address = Column(String(45), nullable=True)
    success = Column(Boolean, default=False, nullable=False)
    attempted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    user_agent = Column(String(255), nullable=True)


class LoginAlert(Base):
    """Alertas de login sospechoso."""
    __tablename__ = "login_alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    device = Column(String(200), nullable=False)
    location = Column(String(200), nullable=True)
    ip_address = Column(String(45), nullable=False)
    user_agent = Column(Text, nullable=True)
    
    is_suspicious = Column(Boolean, default=False, nullable=False)
    is_new_device = Column(Boolean, default=False, nullable=False)
    is_new_location = Column(Boolean, default=False, nullable=False)
    
    notification_sent = Column(Boolean, default=False, nullable=False)
    notification_sent_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    
    user = relationship("User", back_populates="login_alerts")

    def __repr__(self):
        return f"<LoginAlert(user_id={self.user_id}, device={self.device}, suspicious={self.is_suspicious})>"


class ActiveSession(Base):
    """Sesiones activas del usuario."""
    __tablename__ = "active_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    access_token_jti = Column(String(255), unique=True, nullable=False, index=True)
    refresh_token_jti = Column(String(255), unique=True, nullable=False, index=True)
    
    device = Column(String(255), nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(Text, nullable=True)
    location = Column(String(255), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_active = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    
    is_current = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    user = relationship("User", back_populates="active_sessions")

    def __repr__(self):
        return f"<ActiveSession(user_id={self.user_id}, device={self.device}, active={self.is_active})>"


class PasswordResetToken(Base):
    """Tokens para recuperación de contraseña."""
    __tablename__ = "password_reset_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    
    user = relationship("User", back_populates="reset_tokens")


class BlacklistedToken(Base):
    """Tokens revocados (logout)."""
    __tablename__ = "blacklisted_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(255), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    blacklisted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
