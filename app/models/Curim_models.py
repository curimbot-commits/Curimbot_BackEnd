from typing import Optional
from sqlalchemy import (
    Boolean, Column, Integer, String, Text, DateTime,
    ForeignKey, Index
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from .base import Base, TimestampMixin

def utc_now():
    return datetime.now(timezone.utc)

class CurimConversation(Base, TimestampMixin):
    """Conversaciones con el asistente Curim."""
    __tablename__ = "Curim_conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    
    user = relationship("User", back_populates="Curim_conversations")
    messages = relationship("CurimMessage", back_populates="conversation", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<CurimConversation(id={self.id}, user_id={self.user_id})>"


class CurimMessage(Base):
    """Mensajes individuales de una conversación."""
    __tablename__ = "Curim_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("Curim_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    
    confidence = Column(Integer, nullable=True)
    sources = Column(Text, nullable=True)
    sources_info = Column(Text, nullable=True) # Almacena JSON con nombres de archivos y puntuaciones
    from_cache = Column(Boolean, default=False, nullable=False)
    processing_time_ms = Column(Integer, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    
    conversation = relationship("CurimConversation", back_populates="messages")
    
    __table_args__ = (
        Index('idx_conversation_created', 'conversation_id', 'created_at'),
    )
    
    def __repr__(self):
        return f"<CurimMessage(id={self.id}, role={self.role})>"


class CurimDocumentIndex(Base, TimestampMixin):
    """Tracking de documentos indexados en Curim."""
    __tablename__ = "Curim_document_index"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    is_indexed = Column(Boolean, default=False, nullable=False)
    index_version = Column(Integer, default=1, nullable=False)
    chunks_count = Column(Integer, default=0, nullable=False)
    last_indexed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    
    document = relationship("Document", back_populates="Curim_index")
    
    def __repr__(self):
        return f"<CurimDocumentIndex(doc={self.document_id}, indexed={self.is_indexed})>"
