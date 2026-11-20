from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, LargeBinary, DateTime,
    ForeignKey, Index, CheckConstraint, Boolean, Float
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.mysql import LONGBLOB, LONGTEXT

from .base import Base, TimestampMixin
from app.enums.enums import FileType, AIChannel, AIInteractionStatus

def utc_now():
    return datetime.now(timezone.utc)


class Document(Base, TimestampMixin):
    """Modelo de documento."""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), index=True, nullable=False)
    mimetype = Column(String(100), nullable=False)
    size = Column(Integer, default=0, nullable=False)
    file_type = Column(SqlEnum(FileType, name="file_type_enum"), nullable=False)
    text = Column(LONGTEXT, nullable=True)
    blob_enc = Column(LONGBLOB, nullable=True)
    encryption_version = Column(Integer, default=1, nullable=False)
    is_public = Column(Integer, default=0, nullable=False)

    content_hash = Column(String(64), nullable=True)

    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="documents")

    last_accessed = Column(DateTime(timezone=True), nullable=True)
    download_count = Column(Integer, default=0, nullable=False)
    view_count = Column(Integer, default=0, nullable=False)

    Curim_index = relationship(
        "CurimDocumentIndex",
        back_populates="document",
        passive_deletes=True,
        uselist=False,
        cascade="all, delete-orphan"
    )

    status = Column(String(20), default="uploaded", nullable=False, index=True)

    __table_args__ = (
        Index('idx_uploaded_by_file_type', 'uploaded_by', 'file_type'),
        Index('idx_documents_uploaded_by_content_hash', 'uploaded_by', 'content_hash'),
        CheckConstraint('size >= 0', name='check_document_size_positive')
    )

    @property
    def uploaded_by_name(self) -> Optional[str]:
        return self.owner.name if self.owner else None


class AIInteractionLog(Base):
    """
    Registro de interacciones del usuario con la IA (Curim).

    Reemplaza al antiguo ActivityLog. Guarda pregunta, respuesta, canal,
    confianza, fuentes usadas, estado, tiempo de procesamiento, etc.

    Sirve como vista plana/resumida para el historial de actividad,
    facilitando filtrado y paginación sin recorrer conversaciones completas.
    """
    __tablename__ = "ai_interaction_logs"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)  

    channel = Column(
        SqlEnum(AIChannel, name="ai_channel_enum"),
        nullable=False,
        default=AIChannel.text,
        index=True
    )

    confidence = Column(Float, nullable=True) 

    status = Column(
        SqlEnum(AIInteractionStatus, name="ai_interaction_status_enum"),
        nullable=False,
        default=AIInteractionStatus.success,
        index=True
    )

    error_message = Column(Text, nullable=True)

    sources = Column(Text, nullable=True)      
    sources_info = Column(Text, nullable=True)  

    processing_time_ms = Column(Integer, nullable=True)
    from_cache = Column(Boolean, default=False, nullable=False)

    conversation_id = Column(
        Integer,
        ForeignKey("curim_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    timestamp = Column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True
    )

    # Relaciones
    user = relationship("User", back_populates="ai_interactions")
    conversation = relationship("CurimConversation")

    __table_args__ = (
        Index('idx_ai_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_ai_channel_status', 'channel', 'status'),
    )

    def __repr__(self):
        return f"<AIInteractionLog(id={self.id}, user_id={self.user_id}, channel={self.channel}, status={self.status})>"