from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, LargeBinary, DateTime,
    ForeignKey, Index, CheckConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.mysql import LONGBLOB, LONGTEXT

from .base import Base, TimestampMixin
from app.enums.enums import FileType

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
    is_public = Column(Integer, default=0, nullable=False) # 0: private, 1: public

    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="documents")

    last_accessed = Column(DateTime(timezone=True), nullable=True)
    download_count = Column(Integer, default=0, nullable=False)
    view_count = Column(Integer, default=0, nullable=False)

    activities = relationship("ActivityLog", back_populates="document", passive_deletes=True)
    Curim_index = relationship("CurimDocumentIndex", back_populates="document", passive_deletes=True, uselist=False, cascade="all, delete-orphan")
    
    status = Column(String(20), default="uploaded", nullable=False, index=True)
    
    __table_args__ = (
        Index('idx_uploaded_by_file_type', 'uploaded_by', 'file_type'),
        CheckConstraint('size >= 0', name='check_document_size_positive')
    )
    
    @property
    def uploaded_by_name(self) -> Optional[str]:
        return self.owner.name if self.owner else None


class ActivityLog(Base):
    """Registro de actividades sobre documentos."""
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(20), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    timestamp = Column(DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    document_name = Column(String(255), nullable=True)
    document_type = Column(SqlEnum(FileType, name="activity_file_type_enum"))

    user = relationship("User", back_populates="activities")
    document = relationship("Document", back_populates="activities", passive_deletes=True)
