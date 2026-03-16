from sqlalchemy.sql import func
from sqlalchemy import Column, DateTime
from app.db.database import Base

class TimestampMixin:
    """
    Mixin para agregar campos de timestamp automáticos.
    """
    created_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )
